import sublime
import sublime_plugin
import unicodedata

# Characters without a Unicode decomposition that NFD + "drop non-ASCII" would lose.
_TRANSLITERATION = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ð": "d", "Ð": "D",
    "ħ": "h", "Ħ": "H", "ı": "i", "ŧ": "t", "Ŧ": "T", "ß": "ss", "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE", "þ": "th", "Þ": "TH",
})


def _parse_int(text, base):
    """int() that also accepts retro prefixes: $FF (hex), %1010 (binary)."""
    text = text.strip().replace("_", "")
    sign = ""
    if text[:1] in "+-":
        sign, text = text[0], text[1:]
    if base == 16 and text.startswith("$"):
        text = text[1:]
    elif base == 2 and text.startswith("%"):
        text = text[1:]
    return int(sign + text, base)


class _BaseSelection(sublime_plugin.TextCommand):
    def run(self, edit):
        regions = [r for r in self.view.sel()
                   if not r.empty() and self.view.substr(r).strip()]

        if not regions:
            sublime.error_message("Please select some text first.")
            return

        # Convert everything first so a failure leaves the buffer untouched.
        results = []
        for region in regions:
            text = self.view.substr(region)
            core = text.strip()
            lead = text[:len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            try:
                results.append((region, lead + self.convert(core) + trail))
            except Exception as e:
                sublime.error_message("Conversion error:\n\n" + str(e))
                return

        # Replace from the end so earlier regions keep their positions.
        for region, result in reversed(results):
            self.view.replace(edit, region, result)

    def is_enabled(self):
        return any(not r.empty() for r in self.view.sel())

    def convert(self, text):
        raise NotImplementedError("convert() must be implemented in subclass")

class AconvDecToHexCommand(_BaseSelection):
    def convert(self, text):
        return hex(int(text))

class AconvDecToBinCommand(_BaseSelection):
    def convert(self, text):
        return bin(int(text))

class AconvHexToDecCommand(_BaseSelection):
    def convert(self, text):
        return str(_parse_int(text, 16))

class AconvHexToBinCommand(_BaseSelection):
    def convert(self, text):
        return bin(_parse_int(text, 16))

class AconvBinToDecCommand(_BaseSelection):
    def convert(self, text):
        return str(_parse_int(text, 2))

class AconvBinToHexCommand(_BaseSelection):
    def convert(self, text):
        return hex(_parse_int(text, 2))

class AconvToUpperCommand(_BaseSelection):
    def run(self, edit):
        # Sublime's own command handles every selection (and empty ones).
        self.view.run_command("upper_case")

    def is_enabled(self):
        return True


class AconvToLowerCommand(_BaseSelection):
    def run(self, edit):
        self.view.run_command("lower_case")

    def is_enabled(self):
        return True


class AconvRemoveDiacriticsCommand(_BaseSelection):
    def convert(self, text):
        normalized = unicodedata.normalize("NFD", text)
        stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return unicodedata.normalize("NFC", stripped)

class AconvToAsciiCommand(_BaseSelection):
    def convert(self, text):
        normalized = unicodedata.normalize("NFD", text.translate(_TRANSLITERATION))
        cleaned = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return cleaned.encode("ascii", "ignore").decode("ascii")
