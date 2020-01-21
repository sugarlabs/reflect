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
import shutil
import time
from configparser import ConfigParser
import json
from gettext import gettext as _

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GConf', '2.0')
gi.require_version('Vte', '2.91')
gi.require_version('Wnck', '3.0')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GObject

from sugar3.activity import activity
from sugar3.activity.widgets import StopButton
from sugar3.activity.widgets import ActivityToolbarButton
from sugar3.graphics.toolbutton import ToolButton
from sugar3.graphics.radiotoolbutton import RadioToolButton
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.graphics.toolbarbox import ToolbarButton
from sugar3.graphics import iconentry
from sugar3.graphics.alert import Alert
from sugar3.graphics.icon import Icon
from sugar3.graphics import style
from sugar3 import profile
from sugar3.datastore import datastore

from gi.repository import TelepathyGLib
import dbus
from dbus.service import signal
from dbus.gobject_service import ExportedGObject
from sugar3.presence import presenceservice
from sugar3.graphics.objectchooser import ObjectChooser

try:
    from sugar3.presence.wrapper import CollabWrapper
except ImportError:
    from textchannelwrapper import CollabWrapper


from reflectwindow import ReflectWindow
import utils

import logging
_logger = logging.getLogger('reflect-activity')

SERVICE = 'org.sugarlabs.Reflect'
IFACE = SERVICE
PATH = '/org/sugarlabs/Reflect'

NEW_REFLECTION_CMD = 'N'
TITLE_CMD = 'T'
STAR_CMD = '*'
TAG_CMD = 't'
COMMENT_CMD = 'c'
REFLECTION_CMD = 'x'
IMAGE_REFLECTION_CMD = 'P'
PICTURE_CMD = 'p'
JOIN_CMD = 'r'
SHARE_CMD = 'R'
ACTIVITY_CMD = 'a'


class ReflectActivity(activity.Activity):
    ''' An activity for reflecting on one's work '''

    def __init__(self, handle):
        ''' Initialize the toolbar '''
        try:
            super(ReflectActivity, self).__init__(handle)
        except dbus.exceptions.DBusException as e:
            _logger.error(str(e))

        logging.error('setting reflection data to []')
        self.reflection_data = []

        self.connect('realize', self.__realize_cb)

        self.font_size = 8

        self.max_participants = 4
        self._setup_toolbars()

        color = profile.get_color()
        color_stroke = color.get_stroke_color()
        color_fill = color.get_fill_color()

        lighter = utils.lighter_color([color_stroke, color_fill])
        darker = 1 - lighter

        if lighter == 0:
            self.bg_color = style.Color(color_stroke)
            self.fg_color = style.Color(color_fill)
        else:
            self.bg_color = style.Color(color_fill)
            self.fg_color = style.Color(color_stroke)

        self.modify_bg(Gtk.StateType.NORMAL, self.bg_color.get_gdk_color())

        self.bundle_path = activity.get_bundle_path()
        self.tmp_path = os.path.join(activity.get_activity_root(), 'instance')

        self.sharing = False
        self._copy_entry = None
        self._paste_entry = None
        self._webkit = None
        self._clipboard_text = ''
        self._fixed = None

        self.initiating = True
        if self.shared_activity:
            # We're joining
            if not self.get_shared():
                self.initiating = False

                self.busy_cursor()
                share_icon = Icon(icon_name='zoom-neighborhood')
                self._joined_alert = Alert()
                self._joined_alert.props.icon = share_icon
                self._joined_alert.props.title = _('Please wait')
                self._joined_alert.props.msg = _('Starting connection...')
                self.add_alert(self._joined_alert)

                # Wait for joined signal
                self.connect("joined", self._joined_cb)

        self._open_reflect_windows()

        self._setup_presence_service()

        # Joiners wait to receive data from sharer
        # Otherwise, load reflections from local store
        if not self.shared_activity:
            self.busy_cursor()
            GObject.idle_add(self._load_reflections)

    def read_file(self, file_path):
        fd = open(file_path, 'r')
        data = fd.read()
        fd.close()
        self.reflection_data = json.loads(data)

    def write_file(self, file_path):
        data = json.dumps(self.reflection_data)
        fd = open(file_path, 'w')
        fd.write(data)
        fd.close()

        self.metadata['font_size'] = str(self.font_size)

    def _load_reflections(self):
        self._find_starred()
        self._reflect_window.load(self.reflection_data)
        self.reset_cursor()

    def _found_obj_id(self, obj_id):
        for item in self.reflection_data:
            if 'obj_id' in item and item['obj_id'] == obj_id:
                return True
        return False

    def reload_data(self, data):
        ''' Reload data after sorting or searching '''
        self._reflection_data = data[:]
        self._reflect_window.reload(self._reflection_data)
        self.reset_scrolled_window_adjustments()

    def _find_starred(self):
        ''' Find all the _stars in the Journal. '''
        self.dsobjects, self._nobjects = datastore.find({'keep': '1'})
        for dsobj in self.dsobjects:
            if self._found_obj_id(dsobj.object_id):
                continue  # Already have this object -- TODO: update it
            self._add_new_from_journal(dsobj)

    def _add_new_from_journal(self, dsobj):
        self.reflection_data.append({
            'title': _('Untitled'), 'obj_id': dsobj.object_id})
        if hasattr(dsobj, 'metadata'):
            if 'creation_time' in dsobj.metadata:
                self.reflection_data[-1]['creation_time'] = \
                    dsobj.metadata['creation_time']
            else:
                self.reflection_data[-1]['creation_time'] = \
                    int(time.time())
            if 'timestamp' in dsobj.metadata:
                self.reflection_data[-1]['modification_time'] = \
                    dsobj.metadata['timestamp']
            else:
                self.reflection_data[-1]['modification_time'] = \
                    self.reflection_data[-1]['creation_time']
            if 'activity' in dsobj.metadata:
                self.reflection_data[-1]['activities'] = \
                    [utils.bundle_id_to_icon(dsobj.metadata['activity'])]
            if 'title' in dsobj.metadata:
                self.reflection_data[-1]['title'] = \
                    dsobj.metadata['title']
            if 'description' in dsobj.metadata:
                self.reflection_data[-1]['content'] = \
                    [{'text': dsobj.metadata['description']}]
            else:
                self.reflection_data[-1]['content'] = []
            if 'tags' in dsobj.metadata:
                self.reflection_data[-1]['tags'] = []
                tags = dsobj.metadata['tags'].split()
                for tag in tags:
                    if tag[0] != '#':
                        self.reflection_data[-1]['tags'].append('#' + tag)
                    else:
                        self.reflection_data[-1]['tags'].append(tag)
            if 'comments' in dsobj.metadata:
                try:
                    comments = json.loads(dsobj.metadata['comments'])
                except BaseException:
                    comments = []
                self.reflection_data[-1]['comments'] = []
                for comment in comments:
                    try:
                        data = {'nick': comment['from'],
                                'comment': comment['message']}
                        if 'icon-color' in comment:
                            colors = comment['icon-color'].split(',')
                            darker = 1 - utils.lighter_color(colors)
                            data['color'] = colors[darker]
                        else:
                            data['color'] = '#000000'
                        self.reflection_data[-1]['comments'].append(data)
                    except BaseException:
                        _logger.debug('could not parse comment %s'
                                      % comment)
            if 'mime_type' in dsobj.metadata and \
               dsobj.metadata['mime_type'][0:5] == 'image':
                new_path = os.path.join(self.tmp_path,
                                        dsobj.object_id)
                try:
                    shutil.copy(dsobj.file_path, new_path)
                except Exception as e:
                    logging.error("Couldn't copy %s to %s: %s" %
                                  (dsobj.file_path, new_path, e))
                self.reflection_data[-1]['content'].append(
                    {'image': new_path})
            elif 'preview' in dsobj.metadata:
                pixbuf = utils.get_pixbuf_from_journal(dsobj, 300, 225)
                if pixbuf is not None:
                    path = os.path.join(self.tmp_path,
                                        dsobj.object_id + '.png')
                    utils.save_pixbuf_to_file(pixbuf, path)
                    self.reflection_data[-1]['content'].append(
                        {'image': path})
            self.reflection_data[-1]['stars'] = 0

    def delete_item(self, obj_id):
        for i, obj in enumerate(self.reflection_data):
            if obj['obj_id'] == obj_id:
                self.reflection_data.remove(self.reflection_data[i])
                return

    def busy_cursor(self):
        self.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))

    def reset_cursor(self):
        self.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.LEFT_PTR))

    def _open_reflect_windows(self):
        # Most things need only be done once
        if self._fixed is None:
            self._fixed = Gtk.Fixed()
            self._fixed.set_size_request(Gdk.Screen.width(),
                                         Gdk.Screen.height())

            # Offsets from the bottom of the screen
            dy1 = 2 * style.GRID_CELL_SIZE
            dy2 = 1 * style.GRID_CELL_SIZE

            self._button_area = Gtk.Alignment.new(0.5, 0, 0, 0)
            self._button_area.set_size_request(Gdk.Screen.width(),
                                               style.GRID_CELL_SIZE)
            self._fixed.put(self._button_area, 0, 0)
            self._button_area.show()

            self._scrolled_window = Gtk.ScrolledWindow()
            self._scrolled_window.set_size_request(
                Gdk.Screen.width(), Gdk.Screen.height() - dy1)
            self._set_scroll_policy()
            self._graphics_area = Gtk.Alignment.new(0.5, 0, 0, 0)
            self._scrolled_window.add_with_viewport(self._graphics_area)
            self._graphics_area.show()
            self._fixed.put(self._scrolled_window, 0, dy2)
            self._scrolled_window.show()

            self._overlay_window = Gtk.ScrolledWindow()
            self._overlay_window.set_size_request(
                style.GRID_CELL_SIZE * 10,
                style.GRID_CELL_SIZE * 6)
            self._overlay_window.modify_bg(
                Gtk.StateType.NORMAL, style.COLOR_WHITE.get_gdk_color())
            self._overlay_window.set_policy(
                Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self._overlay_area = Gtk.Alignment.new(0.5, 0, 0, 0)
            self._overlay_window.add_with_viewport(self._overlay_area)
            self._overlay_area.show()
            x = int((Gdk.Screen.width() - style.GRID_CELL_SIZE * 10) / 2)
            self._fixed.put(self._overlay_window, 0, Gdk.Screen.height())
            self._overlay_window.show()
            self._old_overlay_widget = None

            self._reflect_window = ReflectWindow(self)
            self._reflect_window.show()

            Gdk.Screen.get_default().connect('size-changed',
                                             self._configure_cb)
            self._toolbox.connect('hide', self._resize_hide_cb)
            self._toolbox.connect('show', self._resize_show_cb)

            self._reflect_window.set_events(Gdk.EventMask.KEY_PRESS_MASK)
            self._reflect_window.connect('key_press_event',
                                         self._reflect_window.keypress_cb)
            self._reflect_window.set_can_focus(True)
            self._reflect_window.grab_focus()

        self.set_canvas(self._fixed)
        self._fixed.show()

    def reset_scrolled_window_adjustments(self):
        adj = self._scrolled_window.get_hadjustment()
        if adj is not None:
            adj.set_value(0)
        adj = self._scrolled_window.get_vadjustment()
        if adj is not None:
            adj.set_value(0)

    def load_graphics_area(self, widget):
        self._graphics_area.add(widget)

    def load_button_area(self, widget):
        self._button_area.add(widget)

    def load_overlay_area(self, widget):
        if self._old_overlay_widget is not None:
            self._overlay_area.remove(self._old_overlay_widget)
        self._overlay_area.add(widget)
        self._old_overlay_widget = widget

    def show_overlay_area(self):
        x = int((Gdk.Screen.width() - style.GRID_CELL_SIZE * 10) / 2)
        self._fixed.move(self._overlay_window, x, style.GRID_CELL_SIZE)

    def hide_overlay_area(self):
        self._fixed.move(
            self._overlay_window, 0, Gdk.Screen.height())

    def collapse_overlay_area(self, button, event):
        self._fixed.move(
            self._overlay_window, 0, Gdk.Screen.height())  

    def _resize_hide_cb(self, widget):
        self._resize_canvas(widget, True)

    def _resize_show_cb(self, widget):
        self._resize_canvas(widget, False)

    def _configure_cb(self, event):
        self._fixed.set_size_request(Gdk.Screen.width(), Gdk.Screen.height())
        self._set_scroll_policy()
        self._resize_canvas(None)
        self._reflect_window.reload_graphics()

    def _resize_canvas(self, widget, fullscreen=False):
        # When a toolbar is expanded or collapsed, resize the canvas
        if hasattr(self, '_reflect_window'):
            if self.toolbar_expanded():
                dy1 = 3 * style.GRID_CELL_SIZE
                dy2 = 2 * style.GRID_CELL_SIZE
            else:
                dy1 = 2 * style.GRID_CELL_SIZE
                dy2 = 1 * style.GRID_CELL_SIZE

            if fullscreen:
                dy1 -= 2 * style.GRID_CELL_SIZE
                dy2 -= 2 * style.GRID_CELL_SIZE

            self._scrolled_window.set_size_request(
                Gdk.Screen.width(), Gdk.Screen.height() - dy2)
            self._fixed.move(self._button_area, 0, 0)

        self._about_panel_visible = False

    def toolbar_expanded(self):
        if self.activity_button.is_expanded():
            return True
        elif self.edit_toolbar_button.is_expanded():
            return True
        elif self.view_toolbar_button.is_expanded():
            return True
        return False

    def get_activity_version(self):
        info_path = os.path.join(self.bundle_path, 'activity', 'activity.info')
        try:
            info_file = open(info_path, 'r')
        except Exception as e:
            _logger.error('Could not open %s: %s' % (info_path, e))
            return 'unknown'

        cp = ConfigParser()
        cp.readfp(info_file)

        section = 'Activity'

        if cp.has_option(section, 'activity_version'):
            activity_version = cp.get(section, 'activity_version')
        else:
            activity_version = 'unknown'
        return activity_version

    def get_uid(self):
        if len(self.volume_data) == 1:
            return self.volume_data[0]['uid']
        else:
            return 'unknown'

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''
        self._toolbox = ToolbarBox()

        self.activity_button = ActivityToolbarButton(self)
        self.activity_button.connect('clicked', self._resize_canvas)
        self._toolbox.toolbar.insert(self.activity_button, 0)
        self.activity_button.show()

        self.set_toolbar_box(self._toolbox)
        self._toolbox.show()
        self.toolbar = self._toolbox.toolbar

        view_toolbar = Gtk.Toolbar()
        self.view_toolbar_button = ToolbarButton(
            page=view_toolbar,
            label=_('View'),
            icon_name='toolbar-view')
        self.view_toolbar_button.connect('clicked', self._resize_canvas)
        self._toolbox.toolbar.insert(self.view_toolbar_button, 1)
        view_toolbar.show()
        self.view_toolbar_button.show()

        button = ToolButton('view-fullscreen')
        button.set_tooltip(_('Fullscreen'))
        button.props.accelerator = '<Alt>Return'
        view_toolbar.insert(button, -1)
        button.show()
        button.connect('clicked', self._fullscreen_cb)

        edit_toolbar = Gtk.Toolbar()
        self.edit_toolbar_button = ToolbarButton(
            page=edit_toolbar,
            label=_('Edit'),
            icon_name='toolbar-edit')
        self.edit_toolbar_button.connect('clicked', self._resize_canvas)
        self._toolbox.toolbar.insert(self.edit_toolbar_button, 1)
        edit_toolbar.show()
        self.edit_toolbar_button.show()

        self._copy_button = ToolButton('edit-copy')
        self._copy_button.set_tooltip(_('Copy'))
        self._copy_button.props.accelerator = '<Ctrl>C'
        edit_toolbar.insert(self._copy_button, -1)
        self._copy_button.show()
        self._copy_button.connect('clicked', self._copy_cb)
        self._copy_button.set_sensitive(False)

        self._paste_button = ToolButton('edit-paste')
        self._paste_button.set_tooltip(_('Paste'))
        self._paste_button.props.accelerator = '<Ctrl>V'
        edit_toolbar.insert(self._paste_button, -1)
        self._paste_button.show()
        self._paste_button.connect('clicked', self._paste_cb)
        self._paste_button.set_sensitive(False)

        button = ToolButton('list-add')
        button.set_tooltip(_('Add Item'))
        button.props.accelerator = '<Ctrl>+'
        self._toolbox.toolbar.insert(button, -1)
        button.show()
        button.connect('clicked', self.__add_item_cb)

        self._date_button = RadioToolButton('date-sort', group=None)
        self._date_button.set_tooltip(_('Sort by Date'))
        self._date_button.connect('clicked', self._date_button_cb)
        self._toolbox.toolbar.insert(self._date_button, -1)
        self._date_button.show()

        self._title_button = RadioToolButton('title-sort',
                                             group=self._date_button)
        self._title_button.set_tooltip(_('Sort by Title'))
        self._title_button.connect('clicked', self._title_button_cb)
        self._toolbox.toolbar.insert(self._title_button, -1)
        self._title_button.show()

        self._stars_button = RadioToolButton('stars-sort',
                                             group=self._date_button)
        self._stars_button.set_tooltip(_('Sort by Favourite'))
        self._stars_button.connect('clicked', self._stars_button_cb)
        self._toolbox.toolbar.insert(self._stars_button, -1)
        self._stars_button.show()

        # setup the search options
        self._search_entry = iconentry.IconEntry()
        self._search_entry.set_icon_from_name(iconentry.ICON_ENTRY_PRIMARY,
                                              'system-search')
        self._search_entry.connect('activate', self._search_entry_activated_cb)
        self._search_entry.connect('changed', self._search_entry_changed_cb)
        self._search_entry.add_clear_button()

        tool_item = Gtk.ToolItem()
        tool_item.set_expand(True)
        tool_item.add(self._search_entry)
        self._search_entry.show()
        self._toolbox.toolbar.insert(tool_item, -1)
        tool_item.show()

        self._search_button = ToolButton('dialog-ok')
        self._search_button.set_tooltip(_('Search by Tags'))
        self._search_button.connect('clicked', self._search_button_cb)
        self._toolbox.toolbar.insert(self._search_button, -1)
        self._search_button.show()

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        self._toolbox.toolbar.insert(separator, -1)
        separator.show()

        stop_button = StopButton(self)
        stop_button.props.accelerator = '<Ctrl>q'
        self._toolbox.toolbar.insert(stop_button, -1)
        stop_button.show()

    def _search_button_cb(self, button):
        self.busy_cursor()
        self._do_search()

    def _search_entry_activated_cb(self, entry):
        self.busy_cursor()
        self._do_search()

    def _do_search(self):
        logging.debug('_search_entry_activated_cb')
        if self._search_entry.props.text == '':
            logging.debug('clearing search')
            for item in self.reflection_data:
                item['hidden'] = False
        else:
            tags = self._search_entry.props.text.split()
            for i, tag in enumerate(tags):
                if not tag[0] == '#':
                    tags[i] = '#%s' % tag
            logging.error(tags)
            for item in self.reflection_data:
                hidden = True
                if 'tags' in item:
                    for tag in tags:
                        if tag in item['tags']:
                            hidden = False
                item['hidden'] = hidden
        self.reload_data(self.reflection_data)
        self.reset_cursor()

    def _search_entry_changed_cb(self, entry):
        logging.debug('_search_entry_changed_cb search for \'%s\'',
                      self._search_entry.props.text)
        self.busy_cursor()
        self._do_search_changed()

    def _do_search_changed(self):
        if self._search_entry.props.text == '':
            logging.debug('clearing search')
            for item in self.reflection_data:
                item['hidden'] = False
            self.reload_data(self.reflection_data)
        self.reset_cursor()

    def _title_button_cb(self, button):
        ''' sort by title '''
        self.busy_cursor()
        GObject.idle_add(self._title_sort)

    def _title_sort(self):
        sorted_data = sorted(self.reflection_data,
                             key=lambda item: item['title'].lower())
        self.reload_data(sorted_data)
        self.reset_cursor()

    def _date_button_cb(self, button):
        ''' sort by modification date '''
        self.busy_cursor()
        GObject.idle_add(self._date_sort)

    def _date_sort(self):
        sorted_data = sorted(self.reflection_data,
                             key=lambda item: int(item['modification_time']),
                             reverse=True)
        self.reload_data(sorted_data)
        self.reset_cursor()

    def _stars_button_cb(self, button):
        ''' sort by number of stars '''
        self.busy_cursor()
        GObject.idle_add(self._stars_sort)

    def _stars_sort(self):
        sorted_data = sorted(self.reflection_data,
                             key=lambda item: item['stars'], reverse=True)
        self.reload_data(sorted_data)
        self.reset_cursor()

    def __realize_cb(self, window):
        self.window_xid = window.get_window().get_xid()

    def set_copy_widget(self, webkit=None, text_entry=None):
        # Each task is responsible for setting a widget for copy
        if webkit is not None:
            self._webkit = webkit
        else:
            self._webkit = None
        if text_entry is not None:
            self._copy_entry = text_entry
        else:
            self._copy_entry = None

        self._copy_button.set_sensitive(webkit is not None or
                                        text_entry is not None)

    def _copy_cb(self, button):
        if self._copy_entry is not None:
            self._copy_entry.copy_clipboard()
        elif self._webkit is not None:
            self._webkit.copy_clipboard()
        else:
            _logger.debug('No widget set for copy.')

    def set_paste_widget(self, text_entry=None):
        # Each task is responsible for setting a widget for paste
        if text_entry is not None:
            self._paste_entry = text_entry
        self._paste_button.set_sensitive(text_entry is not None)

    def _paste_cb(self, button):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.clipboard_text = clipboard.wait_for_text()
        if self._paste_entry is not None:
            self._paste_entry.paste_clipboard()
        else:
            _logger.debug('No widget set for paste (%s).' %
                          self.clipboard_text)

    def _fullscreen_cb(self, button):
        ''' Hide the Sugar toolbars. '''
        self.fullscreen()

    def __add_item_cb(self, button):
        try:
            chooser = ObjectChooser(parent=self, what_filter=None)
        except TypeError:
            chooser = ObjectChooser(
                None, self._reflection.activity,
                Gtk.DialogFlags.MODAL |
                Gtk.DialogFlags.DESTROY_WITH_PARENT)

        try:
            result = chooser.run()
            if result == Gtk.ResponseType.ACCEPT:
                jobject = chooser.get_selected_object()
                if jobject:
                    self._add_new_from_journal(jobject)
                    self.reload_data(self.reflection_data)
        finally:
            chooser.destroy()
            del chooser

    def _set_scroll_policy(self):
        if Gdk.Screen.width() < Gdk.Screen.height():
            self._scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC,
                                             Gtk.PolicyType.AUTOMATIC)
        else:
            self._scrolled_window.set_policy(Gtk.PolicyType.NEVER,
                                             Gtk.PolicyType.AUTOMATIC)

    def _remove_alert_cb(self, alert, response_id):
        self.remove_alert(alert)

    def _close_alert_cb(self, alert, response_id):
        self.remove_alert(alert)
        if response_id is Gtk.ResponseType.OK:
            self.close()

    def _setup_presence_service(self):
        ''' Setup the Presence Service. '''
        self.pservice = presenceservice.get_instance()

        owner = self.pservice.get_owner()
        self.owner = owner
        self._share = ''
        self.connect('shared', self._shared_cb)
        self.connect('joined', self._joined_cb)

    def _shared_cb(self, activity):
        ''' Either set up initial share...'''
        if self.shared_activity is None:
            _logger.error('Failed to share or join activity ... \
                shared_activity is null in _shared_cb()')
            return

        self.initiating = True
        self._waiting_for_reflections = False
        _logger.debug('I am sharing...')

        self.conn = self.shared_activity.telepathy_conn
        self.tubes_chan = self.shared_activity.telepathy_tubes_chan
        self.text_chan = self.shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        _logger.debug('This is my activity: making a tube...')
        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].OfferDBusTube(
            SERVICE, {})

        self.sharing = True

    def _joined_cb(self, activity):
        ''' ...or join an exisiting share. '''
        if self.shared_activity is None:
            _logger.error('Failed to share or join activity ... \
                shared_activity is null in _shared_cb()')
            return

        if self._joined_alert is not None:
            self.remove_alert(self._joined_alert)
            self._joined_alert = None

        self.initiating = False
        self._waiting_for_reflections = True
        _logger.debug('I joined a shared activity.')

        self.conn = self.shared_activity.telepathy_conn
        self.tubes_chan = self.shared_activity.telepathy_tubes_chan
        self.text_chan = self.shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        _logger.debug('I am joining an activity: waiting for a tube...')
        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].ListTubes(
            reply_handler=self._list_tubes_reply_cb,
            error_handler=self._list_tubes_error_cb)

        self.sharing = True

    def _list_tubes_reply_cb(self, tubes):
        ''' Reply to a list request. '''
        for tube_info in tubes:
            self._new_tube_cb(*tube_info)

    def _list_tubes_error_cb(self, e):
        ''' Log errors. '''
        _logger.error('ListTubes() failed: %s', e)

    def _new_tube_cb(self, id, initiator, type, service, params, state):
        ''' Create a new tube. '''
        _logger.debug('New tube: ID=%d initator=%d type=%d service=%s '
                      'params=%r state=%d', id, initiator, type, service,
                      params, state)

        if (type == telepathy.TUBE_TYPE_DBUS and service == SERVICE):
            if state == telepathy.TUBE_STATE_LOCAL_PENDING:
                self.tubes_chan[
                    telepathy.CHANNEL_TYPE_TUBES].AcceptDBusTube(id)

            self.collab = CollabWrapper(self)
            self.collab.message.connect(self.event_received_cb)
            self.collab.setup()

            if self._waiting_for_reflections:
                self.send_event(JOIN_CMD, {})
                self._joined_alert = Alert()
                self._joined_alert.props.title = _('Please wait')
                self._joined_alert.props.msg = _('Requesting reflections...')
                self.add_alert(self._joined_alert)

    def event_received_cb(self, collab, buddy, msg):
        ''' Data is passed as tuples: cmd:text '''
        command = msg.get("command")
        payload = msg.get("payload")
        logging.debug(command)

        if command == JOIN_CMD:
            # Sharer needs to send reflections database to joiners.
            if self.initiating:
                # Send pictures first.
                for item in self.reflection_data:
                    if 'content' in item:
                        for content in item['content']:
                            if 'image' in content:
                                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                                    content['image'], 120, 90)
                                if pixbuf is not None:
                                    data = utils.pixbuf_to_base64(pixbuf)
                                self.send_event(
                                    PICTURE_CMD, {
                                        "image": os.path.basename(
                                            content['image']), "data": data})
                data = json.dumps(self.reflection_data)
                self.send_event(SHARE_CMD, {"data": data})
        elif command == NEW_REFLECTION_CMD:
            self._reflect_window.add_new_reflection(payload)
        elif command == TITLE_CMD:
            obj_id = payload.get("obj_id")
            title = payload.get("title")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    self._reflect_window.update_title(obj_id, title)
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == TAG_CMD:
            obj_id = payload.get("obj_id")
            data = payload.get("data")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    self._reflect_window.update_tags(obj_id, data)
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == ACTIVITY_CMD:
            obj_id = payload.get("obj_id")
            bundle_id = payload.get("bundle_id")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    self._reflect_window.insert_activity(obj_id, bundle_id)
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == STAR_CMD:
            obj_id = payload.get("obj_id")
            stars = payload.get("stars")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    self._reflect_window.update_stars(obj_id, int(stars))
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == COMMENT_CMD:
            found_the_object = False
            # Receive a comment and associated reflection ID
            obj_id = payload.get("obj_id")
            nick = payload.get("nick")
            color = payload.get("color")
            comment = payload.get("comment")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    if 'comments' not in item:
                        item['comments'] = []
                    data = {'nick': nick, 'comment': comment, 'color': color}
                    item['comments'].append(data)
                    self._reflect_window.insert_comment(obj_id, data)
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == REFLECTION_CMD:
            found_the_object = False
            # Receive a reflection and associated reflection ID
            obj_id = payload.get("obj_id")
            reflection = payload.get("reflection")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    if '' not in item:
                        item['content'] = []
                    item['content'].append({'text': reflection})
                    self._reflect_window.insert_reflection(obj_id, reflection)
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == IMAGE_REFLECTION_CMD:
            found_the_object = False
            # Receive a picture reflection and associated reflection ID
            obj_id = payload.get("obj_id")
            basename = payload.get("basename")
            for item in self.reflection_data:
                if item['obj_id'] == obj_id:
                    found_the_object = True
                    if '' not in item:
                        item['content'] = []
                    item['content'].append(
                        {'image': os.path.join(self.tmp_path, basename)})
                    self._reflect_window.insert_picture(
                        obj_id, os.path.join(self.tmp_path, basename))
                    break
            if not found_the_object:
                logging.error('Could not find obj_id %s' % obj_id)
        elif command == PICTURE_CMD:
            # Receive a picture (MAYBE DISPLAY IT AS IT ARRIVES?)
            basename = payload.get("basename")
            data = payload.get("data")
            utils.base64_to_file(data, os.path.join(self.tmp_path, basename))
        elif command == SHARE_CMD:
            # Joiner needs to load reflection database.
            if not self.initiating:
                # Note that pictures should be received.
                self.reflection_data = payload
                self._reflect_window.load(self.reflection_data)
                self._waiting_for_reflections = False
                self.reset_cursor()
                if self._joined_alert is not None:
                    self.remove_alert(self._joined_alert)
                    self._joined_alert = None

    def send_event(self, command, data):
        ''' Send event through the tube. '''
        if hasattr(self, 'collab') and self.collab is not None:
            data["command"] = command
            self.collab.post(data)


class ChatTube(ExportedGObject):
    ''' Class for setting up tube for sharing '''

    def __init__(self, tube, is_initiator, stack_received_cb):
        super(ChatTube, self).__init__(tube, PATH)
        self.tube = tube
        self.is_initiator = is_initiator  # Are we sharing or joining activity?
        self.stack_received_cb = stack_received_cb
        self.stack = ''

        self.tube.add_signal_receiver(self.send_stack_cb, 'SendText', IFACE,
                                      path=PATH, sender_keyword='sender')

    def send_stack_cb(self, text, sender=None):
        if sender == self.tube.get_unique_name():
            return
        self.stack = text
        self.stack_received_cb(text)

    @signal(dbus_interface=IFACE, signature='s')
    def SendText(self, text):
        self.stack = text
