#!/usr/bin/env python
#
# Copyright (c) 2013 Walter Bender, Raul Gutierrez Segales

#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:

#The above copyright notice and this permission notice shall be included in
#all copies or substantial portions of the Software.

#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#THE SOFTWARE.

from gettext import gettext as _
import logging
import os
import tempfile
# import time
import json

from gi.repository import Gtk
from gi.repository import GdkPixbuf
from gi.repository import GConf
from gi.repository import GObject

from sugar3.datastore import datastore
from sugar3.graphics.alert import NotifyAlert
from sugar3.graphics.icon import Icon
from sugar3.graphics.menuitem import MenuItem

from jarabe.journal import journalwindow
from jarabe.webservice import account, accountsmanager

ACCOUNT_NEEDS_ATTENTION = 0
ACCOUNT_ACTIVE = 1
ACCOUNT_NAME = _('Facebook')
COMMENTS = 'comments'
COMMENT_IDS = 'fb_comment_ids'


class Account(account.Account):

    ACCESS_TOKEN_KEY = "/desktop/sugar/collaboration/facebook_access_token"
    ACCESS_TOKEN_KEY_EXPIRATION_DATE = \
        "/desktop/sugar/collaboration/facebook_access_token_expiration_date"

    def __init__(self):
        self.facebook = accountsmanager.get_service('facebook')
        self._client = GConf.Client.get_default()
        self.facebook.FbAccount.set_access_token(self._access_token())
        self._shared_journal_entry = None

    def get_description(self):
        return ACCOUNT_NAME

    def get_token_state(self):
        import time

        now = time.time()

        if self._access_token() is None:
            return self.STATE_NONE
        expiration_date = \
            self._client.get_int(self.ACCESS_TOKEN_KEY_EXPIRATION_DATE)
        if expiration_date != 0 and expiration_date > now:
            return self.STATE_VALID
        else:
            return self.STATE_EXPIRED

    def _access_token(self):
        return self._client.get_string(self.ACCESS_TOKEN_KEY)

    def get_shared_journal_entry(self):
        if self._shared_journal_entry is None:
            self._shared_journal_entry = _SharedJournalEntry(self)
        return self._shared_journal_entry


class _SharedJournalEntry(account.SharedJournalEntry):
    __gsignals__ = {
        'transfer-state-changed': (GObject.SignalFlags.RUN_FIRST, None,
                                   ([str])),
    }

    def __init__(self, fbaccount):
        self._account = fbaccount
        self._alert = None

    def get_share_menu(self, journal_entry_metadata):
        menu = _ShareMenu(
            self._account.facebook,
            journal_entry_metadata,
            self._account.get_token_state() == self._account.STATE_VALID)
        self._connect_transfer_signals(menu)
        return menu

    def get_refresh_menu(self):
        menu = _RefreshMenu(
            self._account.facebook,
            self._account.get_token_state() == self._account.STATE_VALID)
        self._connect_transfer_signals(menu)
        return menu

    def _connect_transfer_signals(self, transfer_widget):
        transfer_widget.connect('transfer-state-changed',
                                self._transfer_state_changed_cb)

    def _transfer_state_changed_cb(self, widget, state_message):
        logging.debug('_transfer_state_changed_cb')

        # First, remove any existing alert
        if self._alert is None:
            self._alert = NotifyAlert()
            self._alert.props.title = ACCOUNT_NAME
            self._alert.connect('response', self._alert_response_cb)
            journalwindow.get_journal_window().add_alert(self._alert)
            self._alert.show()

        logging.debug(state_message)
        self._alert.props.msg = state_message

    def _alert_response_cb(self, alert, response_id):
        journalwindow.get_journal_window().remove_alert(alert)
        self._alert = None


class _ShareMenu(MenuItem):
    __gsignals__ = {
        'transfer-state-changed': (GObject.SignalFlags.RUN_FIRST, None,
                                   ([str])),
    }

    def __init__(self, account, metadata, is_active):
        MenuItem.__init__(self, ACCOUNT_NAME)

        self._facebook = account
        if is_active:
            icon_name = 'facebook-share'
        else:
            icon_name = 'facebook-share-insensitive'
        self.set_image(Icon(icon_name=icon_name,
                            icon_size=Gtk.IconSize.MENU))
        self.show()
        self._metadata = metadata
        self._comment = '%s: %s' % (self._get_metadata_by_key('title'),
                                    self._get_metadata_by_key('description'))

        self.connect('activate', self._facebook_share_menu_cb)

    def _get_metadata_by_key(self, key, default_value=''):
        if key in self._metadata:
            return self._metadata[key]
        return default_value

    def _facebook_share_menu_cb(self, menu_item):
        logging.debug('_facebook_share_menu_cb')

        self.emit('transfer-state-changed', _('Upload started'))
        tmp_file = tempfile.mktemp()
        self._image_file_from_metadata(tmp_file)

        photo = self._facebook.FbPhoto()
        photo.connect('photo-created', self._photo_created_cb, tmp_file)
        photo.connect('photo-create-failed',
                      self._photo_create_failed_cb,
                      tmp_file)

        GObject.idle_add(photo.create, tmp_file)

    def _photo_created_cb(self, fb_photo, fb_object_id, tmp_file):
        logging.debug("_photo_created_cb")

        if os.path.exists(tmp_file):
            os.unlink(tmp_file)

        fb_photo.connect('comment-added', self._comment_added_cb)
        fb_photo.connect('comment-add-failed', self._comment_add_failed_cb)
        fb_photo.add_comment(str(self._comment))

        try:
            ds_object = datastore.get(self._metadata['uid'])
            ds_object.metadata['fb_object_id'] = fb_object_id
            datastore.write(ds_object, update_mtime=False)
        except Exception as ex:
            logging.debug("_photo_created_cb failed to write to datastore: " %
                          str(ex))

    def _photo_create_failed_cb(self, fb_photo, failed_reason, tmp_file):
        logging.debug("_photo_create_failed_cb")

        if os.path.exists(tmp_file):
            os.unlink(tmp_file)

    def _comment_added_cb(self, fb_photo, fb_comment_id):
        logging.debug("_comment_added_cb")

    def _comment_add_failed_cb(self, fb_photo, failed_reason):
        logging.debug("_comment_add_failed_cb")

    def _image_file_from_metadata(self, image_path):
        """ Load a pixbuf from a Journal object. """
        pixbufloader = \
            GdkPixbuf.PixbufLoader.new_with_mime_type('image/png')
        pixbufloader.set_size(300, 225)
        try:
            pixbufloader.write(self._metadata['preview'])
            pixbuf = pixbufloader.get_pixbuf()
        except Exception as ex:
            logging.debug("_image_file_from_metadata: %s" % (str(ex)))
            pixbuf = None

        pixbufloader.close()
        if pixbuf:
            pixbuf.savev(image_path, 'png', [], [])


class _RefreshMenu(MenuItem):
    __gsignals__ = {
        'transfer-state-changed': (GObject.SignalFlags.RUN_FIRST, None,
                                   ([str])),
        'comments-changed': (GObject.SignalFlags.RUN_FIRST, None, ([str]))
    }

    def __init__(self, account, is_active):
        MenuItem.__init__(self, ACCOUNT_NAME)

        self._facebook = account
        self._is_active = is_active
        self._metadata = None

        if is_active:
            icon_name = 'facebook-refresh'
        else:
            icon_name = 'facebook-refresh-insensitive'
        self.set_image(Icon(icon_name=icon_name,
                            icon_size=Gtk.IconSize.MENU))
        self.show()

        self.connect('activate', self._fb_refresh_menu_clicked_cb)

    def set_metadata(self, metadata):
        self._metadata = metadata
        if self._is_active:
            if self._metadata:
                if 'fb_object_id' in self._metadata:
                    self.set_sensitive(True)
                    icon_name = 'facebook-refresh'
                else:
                    self.set_sensitive(False)
                    icon_name = 'facebook-refresh-insensitive'
                self.set_image(Icon(icon_name=icon_name,
                                    icon_size=Gtk.IconSize.MENU))

    def _fb_refresh_menu_clicked_cb(self, button):
        logging.debug('_fb_refresh_menu_clicked_cb')

        if self._metadata is None:
            logging.debug(
                '_fb_refresh_menu_clicked_cb called without metadata')
            return

        if 'fb_object_id' not in self._metadata:
            logging.debug('_fb_refresh_menu_clicked_cb called without \
fb_object_id in metadata')
            return

        self.emit('transfer-state-changed', _('Download started'))
        fb_photo = self._facebook.FbPhoto(self._metadata['fb_object_id'])
        fb_photo.connect('comments-downloaded',
                         self._fb_comments_downloaded_cb)
        fb_photo.connect('comments-download-failed',
                         self._fb_comments_download_failed_cb)
        GObject.idle_add(fb_photo.refresh_comments)

    def _fb_comments_downloaded_cb(self, fb_photo, comments):
        logging.debug('_fb_comments_downloaded_cb')

        ds_object = datastore.get(self._metadata['uid'])
        if not COMMENTS in ds_object.metadata:
            ds_comments = []
        else:
            ds_comments = json.loads(ds_object.metadata[COMMENTS])
        if not COMMENT_IDS in ds_object.metadata:
            ds_comment_ids = []
        else:
            ds_comment_ids = json.loads(ds_object.metadata[COMMENT_IDS])
        new_comment = False
        for comment in comments:
            if comment['id'] not in ds_comment_ids:
                # TODO: get avatar icon and add it to icon_theme
                ds_comments.append({'from': comment['from'],
                                    'message': comment['message'],
                                    'icon': 'facebook-share'})
                ds_comment_ids.append(comment['id'])
                new_comment = True
        if new_comment:
            ds_object.metadata[COMMENTS] = json.dumps(ds_comments)
            ds_object.metadata[COMMENT_IDS] = json.dumps(ds_comment_ids)
            self.emit('comments-changed', ds_object.metadata[COMMENTS])

        datastore.write(ds_object, update_mtime=False)

    def _fb_comments_download_failed_cb(self, fb_photo, failed_reason):
        logging.debug('_fb_comments_download_failed_cb: %s' % (failed_reason))


def get_account():
    return Account()
