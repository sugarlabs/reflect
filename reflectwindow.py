# -*- coding: utf-8 -*-
# Copyright (c) 2014 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA

import os
import time
import json
from random import uniform
from gettext import gettext as _

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GObject
from gi.repository import GdkPixbuf
from gi.repository import Pango

from sugar3.graphics import style
from sugar3.graphics.icon import EventIcon
from sugar3.datastore import datastore
from sugar3 import profile
from sugar3 import util

import logging
_logger = logging.getLogger('reflect-window')

import utils

BUTTON_SIZE = 30
STAR_SIZE = 20
NUMBER_OF_STARS = 5
ENTRY_WIDTH = 6 * style.GRID_CELL_SIZE
PICTURE_WIDTH = 6 * style.GRID_CELL_SIZE
PICTURE_HEIGHT = int(4.5 * style.GRID_CELL_SIZE)
REFLECTION_WIDTH = 8 * style.GRID_CELL_SIZE

NEW_REFLECTION_CMD = 'N'
TITLE_CMD = 'T'
STAR_CMD = '*'
TAG_CMD = 't'
COMMENT_CMD = 'c'
REFLECTION_CMD = 'x'
IMAGE_REFLECTION_CMD = 'P'
PICTURE_CMD = 'p'
ACTIVITY_CMD = 'a'


class ReflectWindow(Gtk.Alignment):

    def __init__(self, activity):
        Gtk.Alignment.__init__(self)
        self._activity = activity
        self._reflections = []

        self.set_size_request(Gdk.Screen.width() - style.GRID_CELL_SIZE, -1)

        self._reflections_grid = Gtk.Grid()
        self._reflections_grid.set_row_spacing(style.DEFAULT_SPACING)
        self._reflections_grid.set_column_spacing(style.DEFAULT_SPACING)

        self.set(xalign=0.5, yalign=0, xscale=0, yscale=0)
        self.add(self._reflections_grid)
        self._reflections_grid.show()

        self._activity.load_graphics_area(self)

        if self._activity.initiating:
            entry = Gtk.Entry()
            entry.props.placeholder_text = _('Add a reflection')
            entry.connect('activate', self._entry_activate_cb)
            self._reflections_grid.attach(entry, 0, 0, 1, 1)
            entry.show()

    def reload(self, reflection_data):
        logging.debug('reloading reflection data')
        for reflection in self._reflections:
            reflection.graphics.hide()
        self.load(reflection_data)

    def load(self, reflection_data):
        if self._activity.initiating:
            row = 1  # 0 is the entry for new reflections
        else:
            row = 0

        for item in reflection_data:
            if item.get('deleted'):
                reflection_data.remove(item)
                continue

            reflection = Reflection(self._activity, item)
            reflection.set_obj_id()
            self._reflections_grid.attach(
                reflection.get_graphics(), 0, row, 1, 1)
            reflection.refresh()
            self._reflections.append(reflection)
            row += 1

        # Add an empty box at the end to expand the scrolled window
        eb = Gtk.EventBox()
        eb.modify_bg(Gtk.StateType.NORMAL,
                     self._activity.bg_color.get_gdk_color())
        box = Gtk.Box()
        box.set_size_request(ENTRY_WIDTH, int(Gdk.Screen.height() / 2))
        eb.add(box)
        box.show()
        self._reflections_grid.attach(eb, 0, row, 1, 1)
        eb.show()

    def update_title(self, obj_id, text):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.update_title(text)
                break

    def update_stars(self, obj_id, stars):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.update_stars(stars)
                break

    def update_tags(self, obj_id, data):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.add_tags(data)
                break

    def insert_comment(self, obj_id, comment):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.add_new_comment(comment)
                item.graphics.notify_button.show()
                # Update journal entry
                if obj_id[0:4] == 'obj-':
                    break
                try:
                    dsobj = datastore.get(obj_id)
                except Exception as e:
                    logging.error('Could not open %s: %e' % (obj_id, e))
                    break
                if 'comments' in dsobj.metadata:
                    data = json.loads(dsobj.metadata['comments'])
                else:
                    data = []
                data.append({'from': comment['nick'],
                             'message': comment['comment'],
                             'icon-color': '%s,%s' % (
                                 comment['color'], comment['color'])
                             })
                dsobj.metadata['comments'] = json.dumps(data)
                datastore.write(dsobj,
                                update_mtime=False,
                                reply_handler=self.datastore_write_cb,
                                error_handler=self.datastore_write_error_cb)
                break

    def insert_activity(self, obj_id, bundle_id):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.add_activity(bundle_id)
                break

    def insert_reflection(self, obj_id, reflection):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.add_new_reflection(reflection)
                break

    def insert_picture(self, obj_id, path):
        for item in self._reflections:
            if item.obj_id == obj_id:
                item.graphics.add_new_picture(path)
                break

    def _entry_activate_cb(self, entry):
        text = entry.props.text
        self._activity.reflection_data.insert(0, {'title': text})
        reflection = Reflection(self._activity,
                                self._activity.reflection_data[0])
        reflection.set_title(text)
        reflection.set_creation_time()
        reflection.set_obj_id(generate=True)
        reflection.add_activity(
            utils.bundle_id_to_icon('org.sugarlabs.Reflect'))
        reflection.set_stars(0)
        self._reflections_grid.insert_row(1)
        self._reflections_grid.attach(
            reflection.get_graphics(), 0, 1, 1, 1)
        reflection.refresh()
        self._reflections.append(reflection)
        entry.set_text('')
        if self._activity.sharing:
            data = json.dumps(self._activity.reflection_data[0])
            self._activity.send_event(NEW_REFLECTION_CMD, {"data": data})

    def add_new_reflection(self, data):
        reflection_data = json.loads(data)
        self._activity.reflection_data.insert(0, reflection_data)
        reflection = Reflection(self._activity,
                                self._activity.reflection_data[0])
        self._reflections_grid.insert_row(0)
        self._reflections_grid.attach(
            reflection.get_graphics(), 0, 1, 1, 1)
        reflection.refresh()
        self._reflections.append(reflection)

    def keypress_cb(self, widget, event):
        self.keyname = Gdk.keyval_name(event.keyval)


class ReflectionGrid(Gtk.EventBox):

    def __init__(self, parent):
        Gtk.EventBox.__init__(self)

        self._reflection = parent
        self._collapse = True
        self._collapse_id = None

        self.modify_bg(
            Gtk.StateType.NORMAL, style.COLOR_WHITE.get_gdk_color())
        self._title_color = self._reflection.activity.fg_color.get_html()

        self._grid = Gtk.Grid()
        self.add(self._grid)
        self._grid.show()

        self._grid.set_row_spacing(style.DEFAULT_PADDING)
        self._grid.set_column_spacing(style.DEFAULT_SPACING)
        self._grid.set_column_homogeneous(True)
        self._grid.set_border_width(style.DEFAULT_PADDING)

        row = 0

        self._expand_button = EventIcon(icon_name='expand',
                                        pixel_size=BUTTON_SIZE)
        self._collapse_id = self._expand_button.connect('button-press-event',
                                                        self._expand_cb)
        self._expand_button.set_tooltip(_('Expand'))
        self._grid.attach(self._expand_button, 0, row, 1, 1)
        self._expand_button.show()

        self._title_align = Gtk.Alignment.new(
            xalign=0, yalign=0.5, xscale=0, yscale=0)
        self._title = Gtk.TextView()
        self._title.set_size_request(ENTRY_WIDTH, -1)
        self._title.set_wrap_mode(Gtk.WrapMode.WORD)
        self._title_tag = self._title.get_buffer().create_tag(
            'title', foreground=self._title_color, weight=Pango.Weight.BOLD,
            size=12288)
        iter_text = self._title.get_buffer().get_iter_at_offset(0)
        self._title.get_buffer().insert_with_tags(
            iter_text, self._reflection.data['title'], self._title_tag)
        if self._reflection.activity.initiating:
            self._title.connect('focus-out-event', self._title_focus_out_cb)
        else:
            self._title.set_editable(False)
        self._title_align.add(self._title)
        self._title.show()
        self._grid.attach(self._title_align, 1, row, 5, 1)
        self._title_align.show()

        delete_button = EventIcon(icon_name='delete', pixel_size=BUTTON_SIZE)
        delete_button.set_tooltip(_('Delete'))
        delete_button.connect('button-press-event', self.__delete_cb)
        self._grid.attach(delete_button, 6, row, 1, 1)
        delete_button.show()

        ''' Notification that a new comment has been shared. '''
        self.notify_button = EventIcon(icon_name='chat',
                                       pixel_size=BUTTON_SIZE)
        self._grid.attach(self.notify_button, 6, row, 1, 1)
        row += 1

        self._time_align = Gtk.Alignment.new(
            xalign=0, yalign=0.5, xscale=0, yscale=0)
        self._time = Gtk.Label()
        self._time.set_size_request(ENTRY_WIDTH, -1)
        self._time.set_justify(Gtk.Justification.LEFT)
        self._time.set_use_markup(True)
        try:
            time_string = util.timestamp_to_elapsed_string(
                int(self._reflection.data['modification_time']))
        except Exception as e:
            logging.error('Could not convert modification time %s: %s' %
                          (self._reflection.data['modification_time'], e))
            self._reflection.data['modification_time'] = \
                self._reflection.data['creation_time']
            time_string = util.timestamp_to_elapsed_string(
                int(self._reflection.data['modification_time']))
        self._time.set_markup(
            '<span foreground="#808080"><small><b>%s</b></small></span>' %
            time_string)
        self._time_align.add(self._time)
        self._time.show()
        self._grid.attach(self._time_align, 1, row, 5, 1)
        self._time_align.show()
        row += 1

        label = ''
        if 'tags' in self._reflection.data:
            for tag in self._reflection.data['tags']:
                if len(label) > 0:
                    label += ', '
                label += tag
        if self._reflection.activity.initiating and label == '':
            label = _('Add a #tag')
        self._tag_align = Gtk.Alignment.new(
            xalign=0, yalign=0.5, xscale=0, yscale=0)
        self._tag_view = Gtk.TextView()
        self._tag_view.set_size_request(ENTRY_WIDTH, -1)
        self._tag_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._tag_view.get_buffer().set_text(label)
        if self._reflection.activity.initiating:
            self._tag_view.connect('focus-in-event', self._tag_focus_in_cb,
                                   _('Add a #tag'))
            self._tag_view.connect('focus-out-event', self._tags_focus_out_cb)
        else:
            self._tag_view.set_editable(False)
        self._tag_align.add(self._tag_view)
        self._tag_view.show()
        self._grid.attach(self._tag_align, 1, row, 5, 1)

        if self._reflection.activity.initiating:
            self._new_tag = EventIcon(icon_name='ok',
                                      pixel_size=BUTTON_SIZE)
            self._new_tag.connect('button-press-event',
                                  self._tag_button_cb)
            self._grid.attach(self._new_tag, 6, row, 1, 1)
        row += 1

        self._activities_align = Gtk.Alignment.new(
            xalign=0, yalign=0.5, xscale=0, yscale=0)
        self._make_activities_grid()
        self._grid.attach(self._activities_align, 1, row, 5, 1)
        self._activities_align.show()

        if self._reflection.activity.initiating:
            self._new_activity = EventIcon(icon_name='add-item',
                                           pixel_size=BUTTON_SIZE)
            self._new_activity.set_tooltip(_('Add new activity'))
            self._new_activity.connect('button-press-event',
                                       self._activity_button_cb)
            self._grid.attach(self._new_activity, 6, row, 1, 1)
            self._new_activity.show()
        row += 1

        self._stars_align = Gtk.Alignment.new(
            xalign=0, yalign=0.5, xscale=0, yscale=0)
        grid = Gtk.Grid()
        if 'stars' in self._reflection.data:
            stars = self._reflection.data['stars']
        else:
            stars = 0
        self._star_icons = []
        for i in range(NUMBER_OF_STARS):
            if i < stars:
                icon_name = 'star-filled'
            else:
                icon_name = 'star-empty'
            self._star_icons.append(EventIcon(icon_name=icon_name,
                                              pixel_size=STAR_SIZE))
            if self._reflection.activity.initiating:
                self._star_icons[-1].connect('button-press-event',
                                             self._star_button_cb, i)
            grid.attach(self._star_icons[-1], i, 0, 1, 1)
            self._star_icons[-1].show()
        self._stars_align.add(grid)
        grid.show()
        self._grid.attach(self._stars_align, 1, row, 5, 1)
        row += 1

        self._content_aligns = []
        first_text = True
        first_image = True
        self._content_we_always_show = []
        if 'content' in self._reflection.data:
            for i, item in enumerate(self._reflection.data['content']):
                # Add edit and delete buttons
                align = Gtk.Alignment.new(
                    xalign=0, yalign=0.5, xscale=0, yscale=0)
                obj = None
                if 'text' in item:
                    obj = Gtk.TextView()
                    obj.set_size_request(ENTRY_WIDTH, -1)
                    obj.set_wrap_mode(Gtk.WrapMode.WORD)

                    obj.get_buffer().set_text(item['text'])
                    if self._reflection.activity.initiating:
                        obj.connect('focus-in-event', self._text_focus_in_cb)
                        obj.connect(
                            'focus-out-event', self._text_focus_out_cb, i)
                    else:
                        obj.set_editable(False)
                    if first_text:
                        self._content_we_always_show.append(align)
                        first_text = False
                elif 'image' in item:
                    try:
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                            item['image'], PICTURE_WIDTH, PICTURE_HEIGHT)
                        obj = Gtk.Image.new_from_pixbuf(pixbuf)
                        if first_image:
                            self._content_we_always_show.append(align)
                            first_image = False
                    except BaseException:
                        logging.error('could not open %s' % item['image'])
                if obj is not None:
                    align.add(obj)
                    obj.show()
                    self._grid.attach(align, 1, row, 5, 1)
                    self._content_aligns.append(align)
                    row += 1

        self._row = row
        if self._reflection.activity.initiating:
            self._new_entry = Gtk.Entry()
            self._new_entry.props.placeholder_text = _('Write a reflection')
            self._new_entry.connect('activate', self._entry_activate_cb)
            self._grid.attach(self._new_entry, 1, row, 5, 1)
            self._content_we_always_show.append(self._new_entry)
            self._new_image = EventIcon(icon_name='add-picture',
                                        pixel_size=BUTTON_SIZE)
            self._new_image.set_tooltip(_('Add new image'))
            self._new_image.connect(
                'button-press-event',
                self._image_button_cb)
            self._grid.attach(self._new_image, 6, row, 1, 1)
            self._content_we_always_show.append(self._new_image)

        for align in self._content_we_always_show:
            align.show()
        row += 1

        self._comment_row = row
        self._comment_aligns = []
        if 'comments' in self._reflection.data:
            for comment in self._reflection.data['comments']:
                obj = Gtk.TextView()
                obj.set_editable(False)
                obj.set_size_request(ENTRY_WIDTH, -1)
                obj.set_wrap_mode(Gtk.WrapMode.WORD)
                nick_tag = obj.get_buffer().create_tag(
                    'nick', foreground=comment['color'],
                    weight=Pango.Weight.BOLD)
                iter_text = obj.get_buffer().get_iter_at_offset(0)
                obj.get_buffer().insert_with_tags(
                    iter_text, comment['nick'] + ': ', nick_tag)
                iter_text = obj.get_buffer().get_end_iter()
                obj.get_buffer().insert(iter_text, comment['comment'])

                align = Gtk.Alignment.new(
                    xalign=0, yalign=0.5, xscale=0, yscale=0)
                align.add(obj)
                obj.show()
                self._grid.attach(align, 1, self._comment_row, 5, 1)
                self._comment_aligns.append(align)
                self._comment_row += 1
        self._new_comment = Gtk.Entry()
        self._new_comment.props.placeholder_text = _('Make a comment')
        self._new_comment.connect('activate', self._comment_activate_cb)
        self._grid.attach(self._new_comment, 1, self._comment_row, 5, 1)

    def _star_button_cb(self, button, event, n):
        self.update_stars(n)
        if self._reflection.activity.sharing:
            self._reflection.activity.send_event(
                STAR_CMD, {"obj_id": self._reflection.data["obj_id"], "stars": n})

    def update_stars(self, n):
        if 'stars' in self._reflection.data:
            oldn = self._reflection.data['stars']
        else:
            oldn = 0
        if n < oldn:  # Erase stars, including one that was clicked
            for i in range(NUMBER_OF_STARS):
                if i < n:
                    icon_name = 'star-filled'
                else:
                    icon_name = 'star-empty'
                self._star_icons[i].set_icon_name(icon_name)
            self._reflection.data['stars'] = n
        else:  # Add stars, including one that was clicked
            for i in range(NUMBER_OF_STARS):
                if i <= n:
                    icon_name = 'star-filled'
                else:
                    icon_name = 'star-empty'
                self._star_icons[i].set_icon_name(icon_name)
            self._reflection.data['stars'] = n + 1
        self._reflection.set_modification_time()

    def _text_focus_in_cb(self, widget, event):
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue = 0.9, 0.9, 0.9
        rgba.alpha = 1.
        widget.override_background_color(Gtk.StateFlags.NORMAL, rgba)

    def _text_focus_out_cb(self, widget, event, entry):
        bounds = widget.get_buffer().get_bounds()
        text = widget.get_buffer().get_text(bounds[0], bounds[1], True)
        self._reflection.data['content'][entry]['text'] = text
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue = 1., 1., 1.
        rgba.alpha = 1.
        widget.override_background_color(Gtk.StateFlags.NORMAL, rgba)

    def _tag_button_cb(self, button, event):
        bounds = self._tag_view.get_buffer().get_bounds()
        text = self._tag_view.get_buffer().get_text(bounds[0], bounds[1], True)
        self._process_tags(self._tag_view.get_buffer(), text)

    def _tag_focus_in_cb(self, widget, event, prompt=None):
        bounds = widget.get_buffer().get_bounds()
        text = widget.get_buffer().get_text(bounds[0], bounds[1], True)
        if text == prompt:
            widget.get_buffer().set_text('')
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue = 0.9, 0.9, 0.9
        rgba.alpha = 1.
        widget.override_background_color(Gtk.StateFlags.NORMAL, rgba)

    def _tags_focus_out_cb(self, widget, event):
        bounds = widget.get_buffer().get_bounds()
        text = widget.get_buffer().get_text(bounds[0], bounds[1], True)
        self._process_tags(widget.get_buffer(), text)
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue = 1., 1., 1.
        rgba.alpha = 1.
        widget.override_background_color(Gtk.StateFlags.NORMAL, rgba)

    def _process_tags(self, text_buffer, text):
        ''' process tag data from textview '''
        self._reflection.data['tags'] = []
        label = ''
        tags = text.split()
        for tag in tags:
            if len(label) > 0:
                label += ', '
            tag = tag.rstrip(',')
            tag = tag.rstrip(';')
            if tag[0] == '#':
                self._reflection.data['tags'].append(tag)
                label += tag
            else:
                self._reflection.data['tags'].append('#' + tag)
                label += '#' + tag
        text_buffer.set_text(label.replace('\12', ''))
        if self._reflection.activity.sharing:
            data = json.dumps(self._reflection.data['tags'])
            self._reflection.activity.send_event(
                TAG_CMD, {"obj_id": self._refelection.data["ob_id"], "reflection": data})
        self._reflection.set_modification_time()

        # Update journal entry
        dsobj = datastore.get(self._reflection.data['obj_id'])
        logging.error('setting tags to %s' % label)
        dsobj.metadata['tags'] = label
        datastore.write(dsobj,
                        update_mtime=False,
                        reply_handler=self.datastore_write_cb,
                        error_handler=self.datastore_write_error_cb)

    def add_tags(self, data):
        ''' process encoded tag data from share '''
        tags = json.loads(data)
        self._reflection.data['tags'] = tags[:]
        label = ''
        for tag in tags:
            if len(label) > 0:
                label += ', '
            label += tag
        self._tag_view.get_buffer().set_text(label)

    def _title_focus_out_cb(self, widget, event):
        ''' process title text from textview '''
        bounds = widget.get_buffer().get_bounds()
        text = widget.get_buffer().get_text(bounds[0], bounds[1], True)
        self._reflection.data['title'] = text
        if self._reflection.activity.sharing:
            self._reflection.activity.send_event(
                TITLE_CMD, {"obj_id": self._reflection.data["obj_id"], "title": text})
        self._reflection.set_modification_time()

        # Update journal entry
        dsobj = datastore.get(self._reflection.data['obj_id'])
        dsobj.metadata['title'] = text
        datastore.write(dsobj,
                        update_mtime=False,
                        reply_handler=self.datastore_write_cb,
                        error_handler=self.datastore_write_error_cb)

    def datastore_write_cb(self):
        logging.debug('ds write cb')

    def datastore_write_error_cb(self, error):
        logging.error('datastore_write_error_cb: %r' % error)

    def update_title(self, text):
        ''' process title text from share '''
        self._reflection.data['title'] = text
        self._title.get_buffer().set_text('')
        iter_text = self._title.get_buffer().get_iter_at_offset(0)
        self._title.get_buffer().insert_with_tags(
            iter_text, text, self._title_tag)

    def _comment_activate_cb(self, entry):
        text = entry.props.text
        if 'comments' not in self._reflection.data:
            self._reflection.data['comments'] = []
        data = {'nick': profile.get_nick_name(),
                'color': self._reflection.activity.fg_color.get_html(),
                'comment': text}
        self._reflection.data['comments'].append(data)
        self.add_new_comment(data)
        # Send the comment
        if self._reflection.activity.sharing:
            send_data = data.copy()
            send_data["obj_id"] = self._reflection.data["obj_id"]
            self._reflection.activity.send_event(COMMENT_CMD, send_data)

        entry.set_text('')

        # Update journal entry
        dsobj = datastore.get(self._reflection.data['obj_id'])
        if 'comments' in dsobj.metadata:
            data = json.loads(dsobj.metadata['comments'])
        else:
            data = []
        data.append({'from': profile.get_nick_name(),
                     'message': text,
                     'icon-color': profile.get_color().to_string()})
        dsobj.metadata['comments'] = json.dumps(data)
        datastore.write(dsobj,
                        update_mtime=False,
                        reply_handler=self.datastore_write_cb,
                        error_handler=self.datastore_write_error_cb)

    def add_new_comment(self, comment):
        obj = Gtk.TextView()
        obj.set_size_request(ENTRY_WIDTH, -1)
        obj.set_wrap_mode(Gtk.WrapMode.WORD)

        nick_tag = obj.get_buffer().create_tag(
            'nick', foreground=comment['color'],
            weight=Pango.Weight.BOLD)
        iter_text = obj.get_buffer().get_iter_at_offset(0)
        obj.get_buffer().insert_with_tags(
            iter_text, comment['nick'] + ': ', nick_tag)
        iter_text = obj.get_buffer().get_end_iter()
        obj.get_buffer().insert(iter_text, comment['comment'])

        align = Gtk.Alignment.new(xalign=0, yalign=0.5, xscale=0, yscale=0)
        align.add(obj)
        obj.show()
        self._grid.insert_row(self._comment_row)
        self._grid.attach(align, 1, self._comment_row, 5, 1)
        self._comment_row += 1
        align.show()

    def _entry_activate_cb(self, entry):
        text = entry.props.text
        if 'content' not in self._reflection.data:
            self._reflection.data['content'] = []
        self._reflection.data['content'].append({'text': text})
        self._reflection.set_modification_time()
        self.add_new_reflection(text)
        # Send the reflection
        if self._reflection.activity.sharing:
            self._reflection.activity.send_event(
                REFLECTION_CMD, {
                    "obj_id": self._reflection.data["obj_id"], "reflection": text})
        entry.set_text('')

    def add_new_reflection(self, text):
        i = len(self._reflection.data['content'])
        obj = Gtk.TextView()
        obj.set_size_request(ENTRY_WIDTH, -1)
        obj.set_wrap_mode(Gtk.WrapMode.WORD)
        obj.get_buffer().set_text(text)
        obj.connect('focus-in-event', self._text_focus_in_cb)
        obj.connect('focus-out-event', self._text_focus_out_cb, i - 1)
        align = Gtk.Alignment.new(xalign=0, yalign=0.5, xscale=0, yscale=0)
        align.add(obj)
        obj.show()
        self._grid.insert_row(self._row)
        self._grid.attach(align, 1, self._row, 5, 1)
        self._row += 1
        align.show()

    def _activity_button_cb(self, button, event):
        self._reflection.activity.busy_cursor()
        GObject.idle_add(self._choose_activity)

    def _choose_activity(self):
        if not hasattr(self, '_activity_sw'):
            grid = Gtk.Grid()
            self._reflection.activity.load_overlay_area(grid)
            grid.show()

            collapse_button = EventIcon(icon_name='delete', pixel_size=BUTTON_SIZE)
            collapse_button.set_tooltip(_('Collapse'))
            collapse_button.connect('button-press-event', self._reflection.activity.collapse_overlay_area)
            grid.attach(collapse_button, 7, 0, 1, 1)
            collapse_button.show()
            bundle_icons = utils.get_bundle_icons()
            x = 0
            y = 1
            for bundle_id in bundle_icons.keys():
                icon_path = bundle_icons[bundle_id]
                if icon_path is None:
                    continue
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                    icon_path, style.GRID_CELL_SIZE, style.GRID_CELL_SIZE)
                image = Gtk.Image.new_from_pixbuf(pixbuf)
                button = Gtk.ToolButton()
                button.set_icon_widget(image)
                image.show()
                button.connect('clicked', self._insert_activity, bundle_id)
                grid.attach(button, x, y, 1, 1)
                button.show()
                x += 1
                if x > 6:
                    y += 1
                    x = 0
        self._reflection.activity.show_overlay_area()
        self._reflection.activity.reset_cursor()

    def _insert_activity(self, widget, bundle_id):
        ''' Add activity from UI '''
        self._reflection.activity.hide_overlay_area()
        self.add_activity(bundle_id)
        if self._reflection.activity.sharing:
            self._reflection.activity.send_event(
                ACTIVITY_CMD, {
                    "obj_id": self._reflection.data["obj_id"], "bundle_id": bundle_id})

    def add_activity(self, bundle_id):
        ''' Add activity from sharer '''
        if 'activities' not in self._reflection.data:
            self._reflection.data['activities'] = []
        self._reflection.data['activities'].append(
            utils.bundle_id_to_icon(bundle_id))
        self._reflection.set_modification_time()
        self._activities_align.remove(self._activities_grid)
        self._make_activities_grid()

    def _make_activities_grid(self):
        column = 0
        self._activities_grid = Gtk.Grid()
        self._activities = []
        if 'activities' in self._reflection.data:
            for icon_path in self._reflection.data['activities']:
                if icon_path is None:
                    continue
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                        icon_path, BUTTON_SIZE, BUTTON_SIZE)
                except Exception as e:
                    logging.error('Could not find icon %s: %s' %
                                  (icon_path, e))
                    continue
                self._activities.append(Gtk.Image.new_from_pixbuf(pixbuf))
                self._activities_grid.attach(
                    self._activities[-1], column, 0, 1, 1)
                self._activities[-1].show()
                column += 1
        else:
            label = Gtk.Label('Add an activity')
            self._activities_grid.attach(label, 0, 0, 5, 1)
            label.show()
        self._activities_align.add(self._activities_grid)
        self._activities_grid.show()

    def _image_button_cb(self, button, event):
        self._reflection.activity.busy_cursor()
        GObject.idle_add(self._choose_image)

    def _choose_image(self):
        from sugar3.graphics.objectchooser import ObjectChooser
        try:
            from sugar3.graphics.objectchooser import FILTER_TYPE_GENERIC_MIME
        except BaseException:
            FILTER_TYPE_GENERIC_MIME = 'generic_mime'
        from sugar3 import mime

        chooser = None
        name = None

        if hasattr(mime, 'GENERIC_TYPE_IMAGE'):
            # See #2398
            if 'image/svg+xml' not in \
                    mime.get_generic_type(mime.GENERIC_TYPE_IMAGE).mime_types:
                mime.get_generic_type(
                    mime.GENERIC_TYPE_IMAGE).mime_types.append('image/svg+xml')
            try:
                chooser = ObjectChooser(parent=self._reflection.activity,
                                        what_filter=mime.GENERIC_TYPE_IMAGE,
                                        filter_type=FILTER_TYPE_GENERIC_MIME,
                                        show_preview=True)
            except BaseException:
                chooser = ObjectChooser(parent=self._reflection.activity,
                                        what_filter=mime.GENERIC_TYPE_IMAGE)
        else:
            try:
                chooser = ObjectChooser(parent=self, what_filter=None)
            except TypeError:
                chooser = ObjectChooser(
                    None, self._reflection.activity,
                    Gtk.DialogFlags.MODAL |
                    Gtk.DialogFlags.DESTROY_WITH_PARENT)

        if chooser is not None:
            try:
                result = chooser.run()
                if result == Gtk.ResponseType.ACCEPT:
                    jobject = chooser.get_selected_object()
                    if jobject and jobject.file_path:
                        name = jobject.metadata['title']
                        mime_type = jobject.metadata['mime_type']
                        _logger.debug('result of choose: %s (%s)' %
                                      (name, str(mime_type)))
            finally:
                chooser.destroy()
                del chooser

            if name is not None:
                pixbuf = self.add_new_picture(jobject.file_path)
                self._reflection.set_modification_time()
                if self._reflection.activity.sharing and pixbuf is not None:
                    self._reflection.activity.send_event(
                        PICTURE_CMD, {
                            "basename": os.path.basename(
                                jobject.file_path), "data": utils.pixbuf_to_base64(pixbuf)})
                    self._reflection.activity.send_event(
                        IMAGE_REFLECTION_CMD, {
                            "obj_id": self._reflection.data["obj_id"], "basename": os.path.basename(
                                jobject.file_path)})

        self._reflection.activity.reset_cursor()

    def add_new_picture(self, path):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                path, PICTURE_WIDTH, PICTURE_HEIGHT)
            obj = Gtk.Image.new_from_pixbuf(pixbuf)
        except BaseException:
            logging.error('could not open %s' % path)
            return None

        align = Gtk.Alignment.new(
            xalign=0, yalign=0.5, xscale=0, yscale=0)
        align.add(obj)
        obj.show()
        self._grid.insert_row(self._row)
        self._grid.attach(align, 1, self._row, 5, 1)
        self._row += 1
        align.show()
        if 'content' not in self._reflection.data:
            self._reflection.data['content'] = []
        self._reflection.data['content'].append({'image': path})

        if self._reflection.activity.sharing:
            return pixbuf

    def _expand_cb(self, button, event):
        self._grid.set_row_spacing(style.DEFAULT_SPACING)
        if self._collapse_id is not None:
            button.disconnect(self._collapse_id)
        button.set_icon_name('collapse')
        button.set_tooltip(_('Collapse'))
        self._collapse_id = button.connect('button-press-event',
                                           self._collapse_cb)
        self._tag_align.show()
        if hasattr(self, '_new_tag'):
            self._new_tag.show()
        self._stars_align.show()
        for align in self._content_aligns:
            align.show()
        for align in self._comment_aligns:
            align.show()
        self._new_comment.show()

    def _collapse_cb(self, button, event):
        self._grid.set_row_spacing(0)
        if self._collapse_id is not None:
            button.disconnect(self._collapse_id)
        button.set_icon_name('expand')
        button.set_tooltip(_('Expand'))
        self._collapse_id = button.connect('button-press-event',
                                           self._expand_cb)
        self._tag_align.hide()
        if hasattr(self, '_new_tag'):
            self._new_tag.hide()
        self._stars_align.hide()
        for align in self._content_aligns:
            if align not in self._content_we_always_show:
                align.hide()
        for align in self._comment_aligns:
            align.hide()
        self._new_comment.hide()

    def __delete_cb(self, button, event):
        self._reflection.activity.delete_item(self._reflection.data['obj_id'])
        self.hide()


class Reflection():
    ''' A class to hold a reflection '''

    def __init__(self, activity, data):
        self.activity = activity
        self.data = data  # dictionary entry for this reflection
        self.creation_time = None
        self.modification_time = None
        self.obj_id = None

    def set_hidden(self, hidden):
        self.data['hidden'] = hidden

    def set_title(self, title):
        self.data['title'] = title

    def set_obj_id(self, generate=False):
        if generate:
            self.data['obj_id'] = 'obj-%d' % int(uniform(0, 10000))
        self.obj_id = self.data['obj_id']

    def set_creation_time(self):
        self.data['creation_time'] = int(time.time())
        if 'modification_time' not in self.data:
            self.data['modification_time'] = self.data['creation_time']

    def set_modification_time(self):
        self.data['modification_time'] = int(time.time())

    def add_tag(self, tag):
        ''' a #tag '''
        self.data['tags'].append(tag)

    def add_text(self, text):
        ''' simple text '''
        self.data['content'].append({'text': text})

    def add_comment(self, text):
        ''' simple text '''
        self.data['comments'].append(text)

    def add_image(self, image):
        ''' an image file pathname '''
        self.data['content'].append({'image': image})

    def search_tags(self, tag):
        return tag in self.data['tags']

    def add_activity(self, activity):
        if 'activities' not in self.data:
            self.data['activities'] = []
        self.data['activities'].append(activity)

    def set_stars(self, n):
        ''' # of stars to highlight '''
        if n < 0:
            n = 0
        elif n > 5:
            n = 5
        self.data['stars'] = n

    def get_graphics(self):
        ''' return resizable entry '''
        self.graphics = ReflectionGrid(self)
        return self.graphics

    def refresh(self):
        ''' redraw graphics with updated content '''
        self.graphics.set_size_request(REFLECTION_WIDTH, -1)
        if 'hidden' in self.data and self.data['hidden']:
            self.graphics.hide()
        else:
            self.graphics.show()
