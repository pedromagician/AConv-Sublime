import sublime
import sublime_plugin
import subprocess
import os
import unicodedata

class AconvBaseSelectionCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        sel_region = self.view.sel()[0]
        sel_text = self.view.substr(sel_region)

        if sel_region.empty() or not sel_text.strip():
            sublime.error_message("Please select some text first.")
            return

        try:
            result = self.convert(sel_text.strip())
        except Exception as e:
            sublime.error_message("Conversion error:\n\n" + str(e))
            return

        self.view.run_command("insert", {"characters": result})

    def convert(self, text):
        raise NotImplementedError("convert() must be implemented in subclass")

class AconvDecToHexCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return hex(int(text))

class AconvDecToBinCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return bin(int(text))

class AconvHexToDecCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return str(int(text, 16))

class AconvHexToBinCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return bin(int(text, 16))

class AconvBinToDecCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return str(int(text, 2))

class AconvBinToHexCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return hex(int(text, 2))

class AconvToUpperCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return text.upper()

class AconvToLowerCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        return text.lower()

class AconvRemoveDiacriticsCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        normalized = unicodedata.normalize("NFD", text)
        return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")

class AconvToAsciiCommand(AconvBaseSelectionCommand):
    def convert(self, text):
        normalized = unicodedata.normalize("NFD", text)
        cleaned = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return cleaned.encode("ascii", "ignore").decode("ascii")
