#!/usr/bin/env python
#
# Copyright (c) 2012 Raul Gutierrez S. - rgs@itevenworks.net

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

import json
import logging
import pycurl
import time
import urllib

from gi.repository import GObject


class FbAccount():
    _access_token = ""

    @classmethod
    def set_access_token(cls, access_token):
        cls._access_token = access_token

    @classmethod
    def access_token(cls):
        return cls._access_token


class FbObjectNotCreatedException(Exception):
    pass


class FbBadCall(Exception):
    pass

FB_TRANSFER_DOWNLOAD = 0
FB_TRANSFER_UPLOAD = 1

FB_PHOTO = 0
FB_COMMENT = 1
FB_LIKE = 2
FB_STATUS = 3

FB_TYPES = {
    FB_PHOTO: "photo",
    FB_COMMENT: "comment",
    FB_LIKE: "like",
    FB_STATUS: "status",
}


class FbPhoto(GObject.GObject):
    PHOTOS_URL = "https://graph.facebook.com/me/photos?access_token=%s"
    COMMENTS_URL = "https://graph.facebook.com/%s/comments"

    __gsignals__ = {
        'photo-created': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'photo-create-failed': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'comment-added': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'comment-add-failed': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'comments-downloaded': (GObject.SignalFlags.RUN_FIRST, None,
                                ([object])),
        'comments-download-failed': (GObject.SignalFlags.RUN_FIRST, None,
                                     ([str])),
        'likes-downloaded': (GObject.SignalFlags.RUN_FIRST, None,
                             ([object])),
        'transfer-started': (GObject.SignalFlags.RUN_FIRST, None,
                             ([int, int])),
        'transfer-progress': (GObject.SignalFlags.RUN_FIRST, None,
                              ([int, int, float])),
        'transfer-completed': (GObject.SignalFlags.RUN_FIRST, None,
                               ([int, int])),
        'transfer-failed': (GObject.SignalFlags.RUN_FIRST, None,
                            ([int, int, str])),
        'transfer-state-changed': (GObject.SignalFlags.RUN_FIRST, None,
                                   ([str])),
    }

    def __init__(self, fb_object_id=None):
        GObject.GObject.__init__(self)
        self.fb_object_id = fb_object_id

    def create(self, image_path):
        GObject.idle_add(self._create, image_path)

    def add_comment(self, comment):
        self.check_created('add_comment')
        GObject.idle_add(self._add_comment, comment)

    def refresh_comments(self):
        """ raise an exception if no one is listening """
        self.check_created('refresh_comments')
        GObject.idle_add(self._refresh_comments)

    def check_created(self, method_name):
        if self.fb_object_id is None:
            errmsg = "Need to call create before calling %s" % (method_name)
            raise FbObjectNotCreatedException(errmsg)

    def _add_comment(self, comment):
        url = self.COMMENTS_URL % (self.fb_object_id)

        response = []

        def write_cb(buf):
            response.append(buf)

        res = self._http_call(url, [('message', comment)], write_cb, True,
                              FB_COMMENT)
        if res == 200:
            try:
                comment_id = self._id_from_response("".join(response))
                self.emit('comment-added', comment_id)
            except FbBadCall as ex:
                self.emit('comment-add-failed', str(ex))
        else:
            logging.debug("_add_comment failed, HTTP resp code: %d" % (res))
            self.emit('comment-add-failed', "Add comment failed: %d" % (res))

    def _create(self, image_path):
        url = self.PHOTOS_URL % (FbAccount.access_token())
        c = pycurl.Curl()
        params = [('source', (c.FORM_FILE, image_path))]

        response = []

        def write_cb(buf):
            response.append(buf)

        result = self._http_call(url, params, write_cb, True, FB_PHOTO)
        if result == 200:
            photo_id = self._id_from_response("".join(response))
            self.fb_object_id = photo_id
            self.emit('photo-created', photo_id)
        else:
            logging.debug("_create failed, HTTP resp code: %d" % result)

            if result == 400:
                failed_reason = "Expired access token."
            elif result == 6:
                failed_reason = "Network is down."
                failed_reason += \
                    "Please connect to the network and try again."
            else:
                failed_reason = "Failed reason unknown: %s" % (str(result))

            self.emit('photo-create-failed', failed_reason)

    def _id_from_response(self, response_str):
        response_object = json.loads(response_str)

        if not "id" in response_object:
            raise FbBadCall(response_str)

        fb_object_id = response_object['id'].encode('ascii', 'replace')
        return fb_object_id

    def _refresh_comments(self):
        """ this blocks """
        url = self.COMMENTS_URL % (self.fb_object_id)

        logging.debug("_refresh_comments fetching %s" % (url))

        response_comments = []

        def write_cb(buf):
            response_comments.append(buf)

        ret = self._http_call(url, [], write_cb, False, FB_COMMENT)
        if ret != 200:
            logging.debug("_refresh_comments failed, HTTP resp code: %d" %
                          ret)
            self.emit('comments-download-failed',
                      "Comments download failed: %d" % (ret))
            return

        logging.debug("_refresh_comments: %s" % ("".join(response_comments)))

        try:
            response_data = json.loads("".join(response_comments))
            if 'data' not in response_data:
                logging.debug("No data inside the FB response")
                self.emit('comments-download-failed',
                          "Comments download failed with no data")
                return
        except Exception as ex:
            logging.debug("Couldn't parse FB response: %s" % str(ex))
            self.emit('comments-download-failed',
                      "Comments download failed: %s" % (str(ex)))
            return

        comments = []
        for c in response_data['data']:
            comment = {}  # this should be an Object
            comment['from'] = c['from']['name']
            comment['message'] = c['message']
            comment['created_time'] = c['created_time']
            comment['like_count'] = c['like_count']
            comment['id'] = c['id']
            comments.append(comment)

        if len(comments) > 0:
            self.emit('comments-downloaded', comments)
        else:
            self.emit('comments-download-failed', 'No comments found')

    def _http_call(self, url, params, write_cb, post, fb_type):
        logging.debug('_http_call')

        app_auth_params = [('access_token', FbAccount.access_token())]

        def f(*args):
            logging.debug('will call _http_progress_cb')
            try:
                args = list(args) + [fb_type]
                logging.debug(args)
                self._http_progress_cb(*args)
            except Exception as ex:
                logging.debug("oops %s" % (str(ex)))

        c = pycurl.Curl()
        c.setopt(c.NOPROGRESS, 0)
        c.setopt(c.PROGRESSFUNCTION, f)
        c.setopt(c.WRITEFUNCTION, write_cb)

        if post:
            c.setopt(c.POST, 1)
            c.setopt(c.HTTPPOST, app_auth_params + params)
            transfer_type = FB_TRANSFER_UPLOAD
            transfer_str = "Upload"
        else:
            c.setopt(c.HTTPGET, 1)
            params_str = urllib.urlencode(app_auth_params + params)
            url = "%s?%s" % (url, params_str)
            transfer_type = FB_TRANSFER_DOWNLOAD
            transfer_str = "Download"

        logging.debug("_http_call: %s" % (url))

        c.setopt(c.URL, url)
        c.perform()

        result = c.getinfo(c.HTTP_CODE)
        if result != 200:
            error_reason = "HTTP Code %d" % (result)
            self.emit('transfer-failed', fb_type, transfer_type, error_reason)
            self.emit('transfer-state-changed', "%s failed: %s" %
                      (transfer_str, error_reason))

        c.close()

        return result

    def _http_progress_cb(self, download_total, download_done,
                          upload_total, upload_done, fb_type):
        logging.debug('_http_progress_cb')

        if download_total != 0:
            total = download_total
            done = download_done
            transfer_type = FB_TRANSFER_DOWNLOAD
            transfer_str = "Download"
        else:
            total = upload_total
            done = upload_done
            transfer_type = FB_TRANSFER_UPLOAD
            transfer_str = "Upload"

        if done == 0:
            self.emit('transfer-started', fb_type, transfer_type)
            state = "started"
        elif done == total:
            self.emit('transfer-completed', fb_type, transfer_type)
            self.emit('transfer-state-changed', "%s completed" %
                      (transfer_str))
            state = "completed"
        else:
            if total != 0:
                self.emit('transfer-progress', fb_type, transfer_type,
                          float(done) / float(total))
                perc = int((float(done) / float(total))*100)
                state = "%d% done" % (perc)

        self.emit('transfer-state-changed', "%s %s" % (transfer_str, state))


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        print "Tests need access_token and an image path!"
        exit(1)

    access_token, photo_path = sys.argv[1:3]
    FbAccount.set_access_token(access_token)


def test_create_photo(loop):
    def photo_created_cb(photo, photo_id, loop):
        print "Photo created: %s" % (photo_id)
        loop.quit()

    photo = FbPhoto()
    photo.connect('photo-created', photo_created_cb, loop)
    photo.create(photo_path)


def test_add_comment(loop):
    def photo_created_cb(photo, photo_id, loop):
        print "Photo created: %s" % (photo_id)

        def comment_added_cb(photo, comment_id, loop):
            print "Comment created: %s" % (comment_id)
            loop.quit()
            return False

        photo = FbPhoto(photo_id)
        photo.connect("comment-added", comment_added_cb, loop)
        photo.add_comment("this is a test")
        return False

    photo = FbPhoto()
    photo.connect('photo-created', photo_created_cb, loop)
    photo.create(photo_path)


def test_get_comments(loop):
    def photo_created_cb(photo, photo_id, loop):
        print "Photo created: %s" % (photo_id)

        def comment_added_cb(photo, comment_id, loop):
            print "Comment created: %s" % (comment_id)

            def comments_downloaded_cb(photo, comments, loop):
                print "%s comments for photo %s" % \
                    (len(comments), photo.fb_object_id)

                for c in comments:
                    print "Comment from %s with message: %s" % \
                        (c["from"], c["message"])

                loop.quit()

            photo.connect('comments-downloaded',
                          comments_downloaded_cb,
                          loop)
            photo.refresh_comments()
            return False

        photo = FbPhoto(photo_id)
        photo.connect("comment-added", comment_added_cb, loop)
        photo.add_comment("this is a test")
        return False

    photo = FbPhoto()
    photo.connect('photo-created', photo_created_cb, loop)
    photo.create(photo_path)


def timeout_cb(test_name, loop):
    print "%s timed out and failed" % (test_name)
    loop.quit()
    return False

if __name__ == '__main__':
    tests = [eval(t) for t in dir() if t.startswith('test_')]

    for t in tests:
        print "\n=== Starting %s (%s) ===" % (t.__name__, time.time())
        loop = GObject.MainLoop()
        tid = GObject.timeout_add(30000, timeout_cb, t.__name__, loop)
        t(loop)
        loop.run()
        GObject.source_remove(tid)
        print "=== Finished %s (%s) ===\n" % (t.__name__, time.time())
