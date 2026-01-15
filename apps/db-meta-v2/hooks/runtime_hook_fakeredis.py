# Runtime hook to fix fakeredis commands.json path in PyInstaller
import os
import sys

# When running in PyInstaller bundle, patch fakeredis to find commands.json
if getattr(sys, 'frozen', False):
    # We're in a PyInstaller bundle
    bundle_dir = sys._MEIPASS

    # Monkey-patch fakeredis._command_info before it's imported
    import fakeredis.model._command_info as cmd_info

    original_load = cmd_info._load_command_info

    def patched_load():
        global _COMMAND_INFO
        import json
        if cmd_info._COMMAND_INFO is None:
            json_path = os.path.join(bundle_dir, "fakeredis", "commands.json")
            with open(json_path, encoding="utf8") as f:
                cmd_info._COMMAND_INFO = cmd_info._encode_obj(json.load(f))

    cmd_info._load_command_info = patched_load
