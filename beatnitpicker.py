#!/usr/bin/python

import os, sys, gobject, stat, time, re
import gtk

import gst, gst.pbutils

from matplotlib.figure import Figure
from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas
import scipy.io.wavfile as wavfile

import wave
import numpy as np

license = """
BeatNitPicker is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 2.

This program is distributed in the hope that it will be useful,
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA)
"""

menu = """
<ui>
    <menubar name="MenuBar">
        <menu action="File">
            <menuitem action="Properties"/>
            <menuitem action="Quit"/>
        </menu>
        <menu action="Edit">
            <menuitem action="Preferences"/>
        </menu>
        <menu action="Help">
            <menuitem action="About"/>
        </menu>
    </menubar>
</ui>
"""

if len(sys.argv) > 1:
    clipath = str(sys.argv[1])
else:
    clipath = False

def bytestomegabytes(bytes):
    return (bytes / 1024) / 1024


def k_to_m(num):
    for x in ['bytes','KB','MB','GB']:
        if num < 1024.0:
            return "%3.1f%s" % (num, x)
        num /= 1024.0
    return "%3.1f%s" % (num, 'TB')


def _wav2array(nchannels, sampwidth, data):
    """data must be the string containing the bytes from the wav file."""
    num_samples, remainder = divmod(len(data), sampwidth * nchannels)
    if remainder > 0:
        raise ValueError('The length of data is not a multiple of '
                         'sampwidth * num_channels.')
        if sampwidth > 4:
            raise ValueError("sampwidth must not be greater than 4.")

    if sampwidth == 3:
        a = np.empty((num_samples, nchannels, 4), dtype=np.uint8)
        raw_bytes = np.fromstring(data, dtype=np.uint8)
        a[:, :, :sampwidth] = raw_bytes.reshape(-1, nchannels, sampwidth)
        a[:, :, sampwidth:] = (a[:, :, sampwidth - 1:sampwidth] >> 7) * 255
        result = a.view('<i4').reshape(a.shape[:-1])
    else:
        # 8 bit samples are stored as unsigned ints; others as signed ints.
        dt_char = 'u' if sampwidth == 1 else 'i'
        a = np.fromstring(data, dtype='<%s%d' % (dt_char, sampwidth))
        result = a.reshape(-1, nchannels)
        return result


def readwav(file):
    """
    Read a wav file.

    Returns the frame rate, sample width (in bytes) and a numpy array
    containing the data.

    This function does not read compressed wav files.
    """
    wav = wave.open(file)
    rate = wav.getframerate()
    nchannels = wav.getnchannels()
    sampwidth = wav.getsampwidth()
    nframes = wav.getnframes()
    data = wav.readframes(nframes)
    wav.close()
    array = _wav2array(nchannels, sampwidth, data)
    return rate, sampwidth, array

class GUI(object):

    column_names = ["Name", "Size", "Mode", "Last Changed"]
    audioFormats = [ ".wav", ".mp3", ".ogg", ".flac", ".MP3", ".FLAC", ".OGG", ".WAV", "wma" ]

    def __init__(self, dname = None):

        if clipath:
            dname = clipath
        else:
            dname = None

        self.window = gtk.Window()
        self.window.set_size_request(550, 600)
        self.window.connect("delete_event", self.on_destroy)
        self.window.set_icon(gtk.icon_theme_get_default().load_icon("gstreamer-properties", 128, 0))

    # lister

        cell_data_funcs = (None, self.file_size, self.file_mode,
                           self.file_last_changed)

        self.list_store = self.make_list(dname)
        self.treeview = gtk.TreeView()

        self.treeview.set_enable_search(True)
        self.treeview.set_search_column(0)

        # self.treeview.set_activate_on_single_click(True)

        self.tvcolumn = [None] * len(self.column_names)
        cellpb = gtk.CellRendererPixbuf()
        self.tvcolumn[0] = gtk.TreeViewColumn(self.column_names[0], cellpb)
        self.tvcolumn[0].set_cell_data_func(cellpb, self.file_pixbuf)
        cell = gtk.CellRendererText()
        self.tvcolumn[0].pack_start(cell, False)
        self.tvcolumn[0].set_cell_data_func(cell, self.file_name)
        self.treeview.append_column(self.tvcolumn[0])

        for n in range(1, len(self.column_names)):
            cell = gtk.CellRendererText()
            self.tvcolumn[n] = gtk.TreeViewColumn(self.column_names[n], cell)


            # make it searchable (does NOT work, please help)
            # self.treeview.set_search_column(True)

            # Allow sorting on the column (does NOT work, please help)
            self.tvcolumn[n].set_sort_column_id(n)

            if n == 1:
                cell.set_property('xalign', 1.0)

            self.tvcolumn[n].set_cell_data_func(cell, cell_data_funcs[n])
            self.treeview.append_column(self.tvcolumn[n])
        self.treeview.set_model(self.list_store)

        self.tree_selection = self.treeview.get_selection()
        self.tree_selection.set_mode(gtk.SELECTION_SINGLE)
        # self.tree_selection.connect("changed", self.open_file)

    # player
        self.label = gtk.Label()
        self.label.set_alignment(0,0.5)
        self.label.set_markup("<b> </b>\n \n ")
        self.label.set_line_wrap(True)

        self.slider = gtk.HScale()
        self.toggle_button = gtk.ToggleButton(None)

        self.next_button = gtk.Button(None)

        self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY, gtk.ICON_SIZE_BUTTON))
        self.next_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_NEXT, gtk.ICON_SIZE_BUTTON))

        self.buttons_hbox = gtk.HBox(False, 5)
        self.slider_hbox = gtk.HBox()
        self.slider.set_range(0, 100)
        self.slider.set_increments(1, 10)

        self.buttons_hbox.pack_start(self.toggle_button, False)
        self.buttons_hbox.pack_start(self.next_button, False)
        self.buttons_hbox.pack_start(self.label, False)
        self.slider_hbox.pack_start(self.slider, True, True)

        self.playbin = gst.element_factory_make('playbin2')
        self.bus = self.playbin.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message::eos", self.on_finish)

        self.is_playing = False

    # end player

    # UI

        scroll_list = gtk.ScrolledWindow()
        scroll_list.add(self.treeview)

        uimanager = gtk.UIManager()
        accelgroup = uimanager.get_accel_group()
        self.window.add_accel_group(accelgroup)

        self.actiongroup = gtk.ActionGroup("uimanager")

        self.actiongroup.add_actions([
            ("Properties", gtk.STOCK_PROPERTIES, "_Properties", None, "File info", self.file_properties_dialog),
            ("Quit", gtk.STOCK_QUIT, "_Quit", None, "Quit the Application", lambda w: gtk.main_quit()),
            ("File", None, "_File"),
            ("Preferences", gtk.STOCK_PREFERENCES, "_Preferences", None, "Edit the Preferences"),
            ("Edit", None, "_Edit"),
            ("About", gtk.STOCK_ABOUT, "_About", None, "yow", self.about_box),
            ("Help", None, "_Help")
        ])

        uimanager.insert_action_group(self.actiongroup, 0)
        uimanager.add_ui_from_string(menu)

        menubar = uimanager.get_widget("/MenuBar")

        # Connects
        self.toggle_button.connect("toggled", self.toggle_play, None, "current", self.treeview, self.tree_selection)
        self.next_button.connect("clicked", self.toggle_play, None, "next", self.treeview, self.tree_selection)
        self.slider.connect('value-changed', self.on_slider_change)
        self.treeview.connect('row-activated', self.open_file)
        # self.treeview.connect("cursor-changed", self.toggle_play, None, "current")

        # Packs
        self.mainbox = gtk.VBox()
        self.plot_inbox = gtk.HBox(True, 0)
        self.plot_outbox = gtk.VBox(True, 0)
        self.plot_outbox.pack_start(self.plot_inbox, True, True, 0)
        self.plot_outbox.set_size_request(200, 60)

        self.mainbox.pack_start(menubar, False)
        self.mainbox.pack_start(self.plot_outbox, False, False, 1)
        self.mainbox.pack_start(self.slider_hbox, False, False, 1)
        self.mainbox.pack_start(self.buttons_hbox, False, False, 1)
        self.mainbox.pack_start(scroll_list, True, True, 1)

        self.window.add(self.mainbox)
        self.window.show_all()
        self.treeview.grab_focus()
        return


    def _wav2array(nchannels, sampwidth, data):
        """data must be the string containing the bytes from the wav file."""
        num_samples, remainder = divmod(len(data), sampwidth * nchannels)
        if remainder > 0:
            raise ValueError('The length of data is not a multiple of '
                             'sampwidth * num_channels.')
        if sampwidth > 4:
            raise ValueError("sampwidth must not be greater than 4.")

        if sampwidth == 3:
            a = np.empty((num_samples, nchannels, 4), dtype=np.uint8)
            raw_bytes = np.fromstring(data, dtype=np.uint8)
            a[:, :, :sampwidth] = raw_bytes.reshape(-1, nchannels, sampwidth)
            a[:, :, sampwidth:] = (a[:, :, sampwidth - 1:sampwidth] >> 7) * 255
            result = a.view('<i4').reshape(a.shape[:-1])
        else:
            # 8 bit samples are stored as unsigned ints; others as signed ints.
            dt_char = 'u' if sampwidth == 1 else 'i'
            a = np.fromstring(data, dtype='<%s%d' % (dt_char, sampwidth))
            result = a.reshape(-1, nchannels)
            return result

    def get_info(self, filename, element=None):
        newitem = gst.pbutils.Discoverer(50000000000)
        info = newitem.discover_uri("file://" + filename)
        tags = info.get_tags()
        tag_string = ""
        if element:
            for tag_name in list(tags.keys()):
                if tag_name == element:
                    tag_string += " " + str(tags[tag_name]) + '\r\n'
                return tag_string
        else:
            for tag_name in list(tags.keys()):
                if tag_name != "image":
                    tag_string += tag_name + " : " + str(tags[tag_name]) + '\r\n'
            return tag_string

    def file_properties_dialog(self, widget):
        filename = self.get_selected_tree_row(self)

        def on_info(self, widget):
            md = gtk.MessageDialog(None,
                                   gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_INFO,
                                   gtk.BUTTONS_CLOSE, "Select something")
            md.run()
            md.destroy()

        if not filename:
            on_info(self, widget)

        if filename.endswith(tuple(self.audioFormats)):
            title = os.path.basename(filename)
            text = self.get_info(filename)
        else:
            title = os.path.basename(filename)
            text = "##", filename, "is not an audio file"

        dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_NONE, title)
        dialog.set_title("BeatNitPicker audio file info")
        dialog.format_secondary_text("Location :" + filename + '\r' + str(text))
        dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
        dialog.connect('destroy', lambda w: dialog.destroy())

        if filename.endswith(".wav") or filename.endswith(".WAV"):
            pa = self.plotter(filename, "waveform", "full")
            pa.set_size_request(350, 200)
            dialog.vbox.pack_start(pa)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def about_box(self, widget):
        about = gtk.AboutDialog()
        about.set_program_name("BeatNitPicker")
        about.set_version("0.2")
        about.set_copyright("(c) Philippe \"xaccrocheur\" Coatmeur")
        about.set_comments("Simple sound sample auditor")
        about.set_website("https://github.com/xaccrocheur")
        about.set_logo(gtk.icon_theme_get_default().load_icon("gstreamer-properties", 128, 0))

        about.set_license(license)
        about.run()
        about.destroy()

    def open_file(self, treeview, path, button, *args):
        model = treeview.get_model()
        iter = model.get_iter(path)
        filename = os.path.join(self.dirname, model.get_value(iter, 0))
        filestat = os.stat(filename)

        if stat.S_ISDIR(filestat.st_mode):
            new_model = self.make_list(filename)
            treeview.set_model(new_model)
        elif filename.endswith(tuple(self.audioFormats)):
            self.toggle_play(self, filename, "current", None, None)
        else:
            print("##", filename, "is not an audio file")

    def get_selected_tree_row(self, *args):
        treeview = self.treeview
        selection = treeview.get_selection()
        (model, pathlist) = selection.get_selected_rows()
        slider_position =  self.slider.get_value()
        for path in pathlist :
            iter = model.get_iter(path)
            filename = os.path.join(self.dirname, model.get_value(iter, 0))
            filestat = os.stat(filename)
            if stat.S_ISDIR(filestat.st_mode):
                print(filename, "is a directory")
            elif filename.endswith(tuple(self.audioFormats)):
                return filename
            else:
                print("##", filename, "is not an audio file")

    def get_next_tree_row(self, *args):
        treeview = self.treeview
        selection = treeview.get_selection()
        (model, pathlist) = selection.get_selected_rows()
        # print "Model: ", model, "Pathlist: ", pathlist, "Longueur: ", pathlist.count()

        slider_position =  self.slider.get_value()
        for path in pathlist :
            iter = model.get_iter(path)
            next_iter = model.iter_next(iter)
            filename = os.path.join(self.dirname, model.get_value(iter, 0))
            next_filename = os.path.join(self.dirname, model.get_value(next_iter, 0))
            filestat = os.stat(next_filename)
            current = filename
            if stat.S_ISDIR(filestat.st_mode):
                # print next_filename, "is a ddirectory"
                # next_filename = self.get_next_tree_row(self)
                # print "current", current
                # print "next", next_filename
                selection.select_iter(next_iter)
                # pass
                # if next_filename != current:
            elif next_filename.endswith(tuple(self.audioFormats)):
                return next_filename
                selection.select_iter(next_iter)
            else:
                print("##", next_filename, "is not an audio file")

    def toggle_play(self, button, filename, position, tv, selection):

        if position == "current":
            # print "current", self.get_next_tree_row(self)
            pass
            # if not self.get_selected_tree_row(self):
                # return
            if filename:
                self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE,  gtk.ICON_SIZE_BUTTON))
                self.player(self, filename)
            else:
                filename = self.get_selected_tree_row(self)
                slider_position =  self.slider.get_value()

                if self.is_playing:
                    self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY,  gtk.ICON_SIZE_BUTTON))
                    self.is_playing = False
                    self.playbin.set_state(gst.STATE_PAUSED)
                else:
                    if slider_position > 0.0:
                        self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE,  gtk.ICON_SIZE_BUTTON))
                        self.playbin.set_state(gst.STATE_PLAYING)
                        gobject.timeout_add(100, self.update_slider)
                        self.is_playing = True
                    else:
                        self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE,  gtk.ICON_SIZE_BUTTON))
                        self.player(self, filename)
                        self.is_playing = True

            re.search('(?<=abc)def', 'abcdef')
            audio_codec_tag = self.get_info(filename, "audio-codec")
            self.label.set_markup("<b> " + os.path.basename(filename) + "</b>\n" + audio_codec_tag)
        else:

            (model, pathlist) = selection.get_selected_rows()

            for path in pathlist :
                iter = model.get_iter(path)
                next_iter = model.iter_next
            filename = self.get_next_tree_row(self)
            if filename:
                myint = reduce(lambda rst, d: rst * 10 + d, path)
                selection.unselect_path(myint)
                selection.select_path(myint + 1)
                print "Filename: ", filename
                self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE,  gtk.ICON_SIZE_BUTTON))
                self.player(self, filename)
                self.is_playing = True
            else:
                print "NO Filename"
                pass

    def player(self, button, filename):
        self.plot_outbox.remove(self.plot_inbox)

        self.playbin.set_state(gst.STATE_READY)
        self.playbin.set_property('uri', 'file:///' + filename)
        self.is_playing = True
        self.playbin.set_state(gst.STATE_PLAYING)
        gobject.timeout_add(100, self.update_slider)

        self.vp = gtk.Viewport()
        self.plot_inbox = gtk.HBox()

        self.mylabel = gtk.Label("No Viz")

        readable = False

        try:
            f = open(filename, 'r')
            w = wavfile.read(open(filename, 'r'))
            readable = True
        except IOError as e:
            print "I/O error({0}): {1}".format(e.errno, e.strerror)
            readable = False
        except ValueError:
            print "Error opening file for plotting: Will not draw waveform."
            readable = False
        except:
            print "Unexpected error:", sys.exc_info()[0]
            readable = False
            raise

        if readable:
            self.pa = self.plotter(filename, "waveform", "neat")
            self.plot_inbox.pack_start(self.pa)
        else:
            self.plot_inbox.pack_start(self.mylabel)

        self.plot_outbox.pack_start(self.plot_inbox, True, True, 0)
        self.window.show_all()

    def plotter(self, filename, plot_type, plot_style):
        rate, data = wavfile.read(open(filename, 'r'), True)
        # rate, data, array = readwav(filename)
        # print("Rate: ", rate)

        f = Figure(facecolor = 'w')
        f.patch.set_alpha(1)
        a = f.add_subplot(111, axisbg='w')

        if plot_type == "waveform":
            a.plot(list(range(len(data))),data, color="OrangeRed",  linewidth=0.5, linestyle="-")
            a.axhline(0, color='DimGray', lw=1)
            a.set_xticklabels(["", ""])
            a.set_yticklabels(["", ""])
        if plot_style == "neat":
            f.subplots_adjust(0, 0, 1, 1)
            a.axis('off')
        canvas = FigureCanvas(f)  # a gtk.DrawingArea
        return canvas

    # Lister funcs

    def lister_compare(self, model, row1, row2, user_data):
        sort_column, _ = model.get_sort_column_id()
        value1 = model.get_value(row1, sort_column)
        value2 = model.get_value(row2, sort_column)
        if value1 < value2:
            return -1
        elif value1 == value2:
            return 0
        else:
            return 1

    def make_list(self, dname=None):
        if not dname:
            self.dirname = os.path.expanduser('~')
        else:
            self.dirname = os.path.abspath(dname)
        self.window.set_title(self.dirname + " - BNP")
        files = [f for f in os.listdir(self.dirname) if f[0] != '.']
        files.sort()
        files = ['..'] + files
        list_store = gtk.ListStore(object)
        for f in files:
            list_store.append([f])
        return list_store

    def file_pixbuf(self, column, cell, model, iter):
        filename = os.path.join(self.dirname, model.get_value(iter, 0))
        filestat = os.stat(filename)
        if stat.S_ISDIR(filestat.st_mode):
            pb = gtk.icon_theme_get_default().load_icon("folder", 24, 0)
        elif filename.endswith(tuple(self.audioFormats)):
            pb = gtk.icon_theme_get_default().load_icon("audio-volume-medium", 24, 0)
        else:
            pb = gtk.icon_theme_get_default().load_icon("edit-copy", 24, 0)
        cell.set_property('pixbuf', pb)
        return

    def file_name(self, column, cell, model, iter):
        cell.set_property('text', model.get_value(iter, 0))
        return

    def file_size(self, column, cell, model, iter):
        filename = os.path.join(self.dirname, model.get_value(iter, 0))
        filestat = os.stat(filename)
        # print("Size: ", bytestomegabytes(filestat.st_size), "Mb")

        size = str(k_to_m(filestat.st_size))
        cell.set_property('text', size)
        return

    def file_mode(self, column, cell, model, iter):
        filename = os.path.join(self.dirname, model.get_value(iter, 0))
        filestat = os.stat(filename)
        cell.set_property('text', oct(stat.S_IMODE(filestat.st_mode)))
        return

    def file_last_changed(self, column, cell, model, iter):
        filename = os.path.join(self.dirname, model.get_value(iter, 0))
        filestat = os.stat(filename)
        cell.set_property('text', time.ctime(filestat.st_mtime))
        return


    # player funcs

    def on_finish(self, bus, message):
        self.playbin.set_state(gst.STATE_PAUSED)
        self.is_playing = False
        self.playbin.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, 0)
        self.slider.set_value(0)
        self.toggle_button.set_property("image", gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY,  gtk.ICON_SIZE_BUTTON))

    def on_destroy(self, *args):
        self.playbin.set_state(gst.STATE_NULL)
        self.is_playing = False
        gtk.main_quit()

    def on_slider_change(self, slider):
        seek_time_secs = self.slider.get_value()
        self.playbin.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH | gst.SEEK_FLAG_KEY_UNIT, seek_time_secs * gst.SECOND)

    def update_slider(self):
        if not self.is_playing:
            return False # cancel timeout

        try:
            self.nanosecs, format = self.playbin.query_position(gst.FORMAT_TIME)
            self.duration_nanosecs, format = self.playbin.query_duration(gst.FORMAT_TIME)

            # block seek handler so we don't seek when we set_value()
            self.slider.handler_block_by_func(self.on_slider_change)

            self.slider.set_range(0, float(self.duration_nanosecs) / gst.SECOND)
            self.slider.set_value(float(self.nanosecs) / gst.SECOND)

            self.slider.handler_unblock_by_func(self.on_slider_change)

        except gst.QueryError:
            # pipeline must not be ready and does not know position
            pass

        return True # continue calling every 30 milliseconds


def main():
    gtk.main()

if __name__ == "__main__":
    GUI()
    main()
