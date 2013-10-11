# Copyright (C) 2013, Walter Bender - Raul Gutierrez Segales
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

import os
import logging
import time
import urllib
import urlparse

from gi.repository import GConf
from gi.repository import Gtk
from gi.repository import WebKit

from jarabe.webservice import accountsmanager
# import webservice.facebook.account
from cpsection.webaccount.web_service import WebService


class WebService(WebService):
    FB_APP_ID = "172917389475707"
    FB_REDIRECT_URI = "http://www.sugarlabs.org"

    def __init__(self):
        logging.debug('GETTING FB ACCOUNT')
        self._account = accountsmanager.get_account('facebook')
        logging.debug(self._account)

    def get_icon_name(self):
        return 'facebook-share'

    def config_service_cb(self, widget, event, container):
        logging.debug('config_service_fb')

        wkv = WebKit.WebView()
        wkv.load_uri(self._fb_auth_url())
        wkv.grab_focus()
        wkv.connect('navigation-policy-decision-requested',
                    self._fb_nav_policy_cb)

        for c in container.get_children():
            container.remove(c)

        scrolled = Gtk.ScrolledWindow()
        scrolled.add(wkv)

        container.add(scrolled)
        container.show_all()

    def _fb_auth_url(self):
        url = 'http://www.facebook.com/dialog/oauth'
        params = [('client_id', self.FB_APP_ID),
                  ('redirect_uri', self.FB_REDIRECT_URI),
                  ('response_type', 'token'),
                  ('scope', 'publish_stream')]

        return "%s?%s" % (url, urllib.urlencode(params))

    def _fb_nav_policy_cb(self, view, frame, req, action, param):
        uri = req.get_uri()
        if uri is None:
            return

        url_o = urlparse.urlparse(uri)
        params = urlparse.parse_qs(url_o.fragment)
        if 'access_token' in params and 'expires_in' in params:
            self._fb_save_access_token(params['access_token'][0],
                                       int(params['expires_in'][0]))

    def _fb_save_access_token(self, access_token, expires_in):
        logging.debug('FB SAVE ACCESS TOKEN')
        client = GConf.Client.get_default()

        # client.set_string(self._account.Account.ACCESS_TOKEN_KEY,
        client.set_string(self._account.ACCESS_TOKEN_KEY,
                          access_token)

        expiry_time = int(time.time()) + expires_in
        client.set_int(
            # self._account.Account.ACCESS_TOKEN_KEY_EXPIRATION_DATE,
            self._account.ACCESS_TOKEN_KEY_EXPIRATION_DATE,
            expiry_time)


def get_service():
    logging.debug('GET FB SERVICE')
    return WebService()
