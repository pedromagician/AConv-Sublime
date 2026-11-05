import sublime
import sublime_plugin
import subprocess
import os
import sys
import threading
import locale

def decode_output(data):
    """Decode AConv.exe console output using the system code page."""
    encoding = locale.getpreferredencoding(False) or "cp1250"
    return data.decode(encoding, errors="replace").replace("\r", "")


def open_read_only(window, path):
    """Open `path` read-only (helper lives in the ToggleReadOnly package)."""
    try:
        from ToggleReadOnly.ReadOnly import open_read_only as helper
    except ImportError:
        return window.open_file(path)
    return helper(window, path)


class AconvRunCommand(sublime_plugin.WindowCommand):
    # AConv.exe interprets backslashes in its arguments as escape sequences
    # (used for escape-sequence dictionaries) and mangles Windows-style
    # paths produced by os.path.join (e.g. "C:\Users\...\dict\x.dict").
    # Forward slashes are accepted fine by Windows/AConv, so normalize
    # every path we hand to the exe.
    def to_exe_path(self, path):
        return path.replace("\\", "/")

    def run_process_async(self, args, callback):
        def fail(message):
            sublime.set_timeout(lambda: sublime.error_message(message), 0)

        def worker():
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            try:
                proc = subprocess.Popen(
                    args, shell=False,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    **kwargs)
                output, _ = proc.communicate()
            except Exception as e:
                fail("Error while running AConv.exe:\n\n" + str(e))
                return

            if proc.returncode != 0:
                text = decode_output(output).strip()
                print(text)
                tail = "\n".join(text.splitlines()[-5:])
                fail("AConv.exe failed (exit code {}):\n\n{}".format(proc.returncode, tail))
                return

            sublime.set_timeout(callback, 0)

        threading.Thread(target=worker, daemon=True).start()

    def finish_conversion(self, ctx):
        # ctx is a snapshot taken when the conversion started, so overlapping
        # conversions do not see each other's state.
        if ctx["mode"] == "clip":
            self.apply_clipboard(ctx)
            return

        open_read_only(self.window, ctx["output_path"])

    def apply_clipboard(self, ctx):
        view = ctx["view"]
        if not view.is_valid():
            sublime.status_message("AConv: the target view was closed.")
            return
        if view.is_read_only():
            sublime.error_message("AConv: the view is read-only, the converted text cannot be inserted.")
            return

        encoding_name = self.ENCODINGS.get(ctx["encoding_tag"])
        if encoding_name:
            view.set_encoding(encoding_name)

        result = sublime.get_clipboard()
        if not ctx["use_only_what_is_selected"]:
            view.run_command("select_all")
        view.run_command("insert", {"characters": result})

        if ctx["line_ending_mode"] == "unix":
            view.set_line_endings("unix")
        elif ctx["line_ending_mode"] == "windows":
            view.set_line_endings("windows")


    def load_config(self, plugin_dir):
        cfg_path = os.path.join(plugin_dir, "AConv.cfg")

        if not os.path.isfile(cfg_path):
            sublime.error_message("AConv.cfg not found.\n\nPlease create the configuration file.")
            return False

        section = None
        config = {
            "GENERAL": {
                "suffix_output_filename": "conv",
                "use_only_what_is_selected": "false"
            },
            "PLATFORMS": [],
            "DIRECTIONS": {},
            "PROFILES": {},
            "PROFILES_WITH_F_ANSI": set(),
            "PROFILES_CLIPBOARD_DISABLED": set(),
            "ENCODINGS": {}
        }

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()

                    if not line or line.startswith(";") or line.startswith("#"):
                        continue

                    # Section header
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1]
                        continue

                    if "=" in line:
                        key, value = [x.strip() for x in line.split("=", 1)]

                        # GENERAL
                        if section == "GENERAL":
                            config["GENERAL"][key] = value

                        # PLATFORMS
                        elif section == "PLATFORMS":
                            config["PLATFORMS"].append((key, value))

                        # DIRECTIONS.<platform>
                        elif section.startswith("DIRECTIONS."):
                            plat = section.split(".", 1)[1]
                            config["DIRECTIONS"].setdefault(plat, [])
                            config["DIRECTIONS"][plat].append((key, value))

                        # PROFILES.<platform>.<mode>
                        elif section.startswith("PROFILES."):
                            _, plat, mode = section.split(".")
                            config["PROFILES"].setdefault(plat, {})
                            config["PROFILES"][plat].setdefault(mode, [])
                            config["PROFILES"][plat][mode].append(
                                (key, value.split())
                            )

                        # ENCODINGS
                        elif section == "ENCODINGS":
                            config["ENCODINGS"][key] = value

                    else:
                        # Sections with list items
                        if section == "PROFILES_WITH_F_ANSI":
                            config["PROFILES_WITH_F_ANSI"].add(line)

                        elif section == "PROFILES_CLIPBOARD_DISABLED":
                            config["PROFILES_CLIPBOARD_DISABLED"].add(line)

            # Every profile ends with "<line ending mode> <encoding tag>".
            for plat, modes in config["PROFILES"].items():
                for mode, profiles in modes.items():
                    for name, args in profiles:
                        if len(args) < 2:
                            raise ValueError(
                                "Profile \"{}\" in [PROFILES.{}.{}] needs a line-ending mode and an encoding tag at the end.".format(
                                    name, plat, mode))

            # Assign to class
            self.PLATFORMS = config["PLATFORMS"]
            self.DIRECTIONS = config["DIRECTIONS"]
            self.PROFILES = config["PROFILES"]
            self.PROFILES_WITH_F_ANSI = config["PROFILES_WITH_F_ANSI"]
            self.PROFILES_CLIPBOARD_DISABLED = config["PROFILES_CLIPBOARD_DISABLED"]
            self.ENCODINGS = config["ENCODINGS"]
            self.suffix_output_filename = config["GENERAL"]["suffix_output_filename"]
            self.use_only_what_is_selected = config["GENERAL"]["use_only_what_is_selected"]

            return True

        except Exception as e:
            sublime.error_message("Error parsing AConv.cfg:\n\n" + str(e))
            return False

    # DETECT
    def run_detect(self):
        input_path = self.view.file_name()
        if not input_path:
            sublime.error_message("No file is currently open.")
            return

        plugin_dir = os.path.dirname(__file__)
        exe = os.path.join(plugin_dir, "AConv.exe")
        dict_path = os.path.join(plugin_dir, "dict", ".dict")

        if not os.path.isfile(exe):
            sublime.error_message("AConv.exe not found.")
            return

        if self.view.is_dirty():
            sublime.status_message("AConv: the file has unsaved changes, the version from disk is used.")

        cmd = [exe, "-i", self.to_exe_path(input_path), "-detect", "-dict", self.to_exe_path(dict_path), "-log", "errors"]

        def worker():
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            try:
                output = subprocess.check_output(
                    cmd, shell=False, stderr=subprocess.STDOUT, **kwargs)
            except Exception as e:
                message = "Detect error:\n\n" + str(e)
                sublime.set_timeout(lambda: sublime.error_message(message), 0)
                return

            buff = decode_output(output)

            def show():
                sublime.active_window().run_command("cls")
                print(buff)
                sublime.message_dialog(buff)

            sublime.set_timeout(show, 0)

        threading.Thread(target=worker, daemon=True).start()

    # 1) PLATFORM
    def run(self):
        plugin_dir = os.path.dirname(__file__)
        if not self.load_config(plugin_dir):
            return

        self.view = self.window.active_view()

        if not self.view:
            sublime.error_message("No file is currently open.")
            return

        items = [["⬜️⬜️⬜️⬜️ Choose a platform", ""]] + [
            [p[0], p[1]] for p in self.PLATFORMS
        ] + [
            ["🔍 Detect encoding", "Auto-detect using dictionary"]
        ]

        self.window.show_quick_panel(items, self.on_platform_selected)

    def on_platform_selected(self, index):
        if index <= 0:
            return

        if index == len(self.PLATFORMS) + 1:
            self.run_detect()
            return

        # Platform ids are the [DIRECTIONS.<id>] section names; the labels in
        # [PLATFORMS] contain the id (e.g. "🌈 ZX Spectrum" -> "ZX").
        label = self.PLATFORMS[index - 1][0].lower()
        self.platform = next(
            (plat for plat in self.DIRECTIONS if plat.lower() in label), None)
        if self.platform is None:
            sublime.error_message(
                "AConv.cfg: no [DIRECTIONS.<platform>] section matches the platform \"{}\".".format(
                    self.PLATFORMS[index - 1][0]))
            return

        self.show_direction_menu()

    # 2) DIRECTION (Windows ↔ Platform)
    def show_direction_menu(self):
        self.directions = self.DIRECTIONS[self.platform]

        items = [["🟩⬜️⬜️⬜️ Select the conversion direction", "Windows <-> " + self.platform]] + [
            [d[0], d[1]] for d in self.directions
        ]

        if self.platform == "Win":
            self.direction = 0
            sublime.status_message("The conversion is only possible in one direction.")
            self.show_profile_menu()
            return

        self.window.show_quick_panel(items, self.on_direction_selected)

    def on_direction_selected(self, index):
        if index <= 0:
            return

        index -= 1
        self.direction = index  # 0 = Win->Platform, 1 = Platform->Win
        self.show_profile_menu()

    # 3) PROFILE (KOI8, E2, …)
    def show_profile_menu(self):
        if self.platform == "Win":
            self.profiles = self.PROFILES["Win"]["w2w"]
        else:
            key = "w2b" if self.direction == 0 else "b2w"
            self.profiles = self.PROFILES[self.platform][key]

        items = [["🟩🟩⬜️⬜️ Select a profile", self.platform + " encoding"]] + [
            [p[0], "It uses a dictionary + transformation"] for p in self.profiles
        ]

        self.window.show_quick_panel(items, self.on_profile_selected)

    def on_profile_selected(self, index):
        if index <= 0:
            return

        index -= 1
        self.selected_profile = index

        profile_name = self.profiles[self.selected_profile][0]

        # Turn off the clipboard
        if profile_name in self.PROFILES_CLIPBOARD_DISABLED:
            self.mode = "disk"
            sublime.status_message("Clipboard mode disabled for this profile.")
            self.on_done()
            return

        self.show_mode_menu()

    # 4) MODE (Disk / Clipboard)
    def show_mode_menu(self):
        modes = [
            ("💾 Disk", "Converting a file to a new file"),
            ("📄 View (Clipboard)", "Converting data from a window using the clipboard"),
        ]

        items = [["🟩🟩🟩⬜️ Select a mode", "Data on the disk or data from the window"]] + [
            [m[0], m[1]] for m in modes
        ]

        self.window.show_quick_panel(items, self.on_mode_selected)

    def on_mode_selected(self, index):
        if index <= 0:
            return

        index -= 1
        self.mode = "disk" if index == 0 else "clip"
        self.on_done()

    # EXECUTION
    def on_done(self):
        input_path = self.view.file_name()
        folder = os.path.dirname(input_path) if input_path else None
        plugin_dir = os.path.dirname(__file__)

        profile_args = list(self.profiles[self.selected_profile][1])

        # Extract encoding tag
        encoding_tag = profile_args[-1]
        profile_args = profile_args[:-1]

        # Extract line enging mode
        line_ending_mode = profile_args[-1]
        profile_args = profile_args[:-1]

        is_clipboard = (self.mode == "clip")

        if not is_clipboard:
            if not input_path:
                sublime.error_message("The file is not saved. Save it first or use the clipboard mode.")
                return

            if self.view.is_dirty():
                sublime.status_message("AConv: the file has unsaved changes, the version from disk is used.")

        suffix = self.suffix_output_filename
        use_only_what_is_selected = (self.use_only_what_is_selected == "true" or self.use_only_what_is_selected == "yes" or self.use_only_what_is_selected == "1")

        if not is_clipboard:
            base, ext = os.path.splitext(os.path.basename(input_path))
            output_filename = "{}.{}{}".format(base, suffix, ext)
            output_path = os.path.join(folder, output_filename)
        else:
            output_path = None

        exe = os.path.join(plugin_dir, "AConv.exe")

        if not os.path.isfile(exe):
            sublime.error_message("AConv.exe not found.")
            return

        if is_clipboard:
            if not use_only_what_is_selected:
                self.view.run_command("select_all")
            self.view.run_command("copy")
            full_args = [exe]
            profile_args = ["-ic", "-oc"] + profile_args
        else:
            full_args = [exe, "-i", self.to_exe_path(input_path), "-o", self.to_exe_path(output_path)]

        profile_name = self.profiles[self.selected_profile][0]

        # -f ansi
        add_f_ansi = (
            not is_clipboard
            and self.direction == 1
            and profile_name in self.PROFILES_WITH_F_ANSI
        )

        fixed_args = []
        for a in profile_args:
            if a.endswith(".dict"):
                dict_name = a

                # clipboard → *_clipboard.dict
                if is_clipboard:
                    base, ext = os.path.splitext(dict_name)
                    dict_name = "clipboard\\" + base + "_clipboard" + ext

                    dict_path = os.path.join(plugin_dir, "dict", dict_name)

                    if not os.path.isfile(dict_path):
                        sublime.error_message("Dictionary file not found:\n\n"+dict_name+"\n\nClipboard mode requires a '*_clipboard.dict' variant.\nPlease create it or disable clipboard mode for this profile.")
                        return

                fixed_args.append(self.to_exe_path(os.path.join(plugin_dir, "dict", dict_name)))
            else:
                fixed_args.append(a)

        # -f ansi
        if add_f_ansi:
            fixed_args.append("-f")
            fixed_args.append("ansi")

        full_args.extend(fixed_args)
        full_args.extend(["-log", "errors"])

        ctx = {
            "mode": self.mode,
            "view": self.view,
            "output_path": output_path,
            "encoding_tag": encoding_tag,
            "line_ending_mode": line_ending_mode,
            "use_only_what_is_selected": use_only_what_is_selected,
        }

        try:
            self.run_process_async(full_args, lambda: self.finish_conversion(ctx))

        except Exception as e:
            sublime.error_message("Error while running AConv.exe:\n" + str(e))
