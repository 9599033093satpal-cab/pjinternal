import os
import sys
import collections
import platform

# Monkeypatch platform universally to prevent hangs
uname_result = collections.namedtuple("uname_result", ["system", "node", "release", "version", "machine", "processor"])
platform.uname = lambda: uname_result("Windows", "localhost", "10", "10.0.19045", "AMD64", "Intel64 Family 6 Model 158 Stepping 10, GenuineIntel")
platform.machine = lambda: "AMD64"
platform.system = lambda: "Windows"
platform.platform = lambda *args, **kwargs: "Windows-10-10.0.19045-SP0"
platform.python_implementation = lambda: "CPython"
platform.python_version = lambda: "3.12.3"

# Inject venv12 site packages and project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
venv_site = os.path.join(project_root, "venv12", "Lib", "site-packages")
if os.path.exists(venv_site):
    sys.path.insert(0, venv_site)

from neural_structurer import NeuralStructurer

# Read Bhavika raw text
text_path = os.path.join("outputs", "146df543-af17-4640-9377-3f07cdf661e4", "Bhavika_1.txt")
if not os.path.exists(text_path):
    print("Error: Bhavika text file not found at", text_path)
    sys.exit(1)

with open(text_path, "r", encoding="utf-8") as f:
    raw_text = f.read()

print("Loaded raw text. Character count:", len(raw_text))

# Let's test NeuralStructurer
structurer = NeuralStructurer()

# Override process_with_openai to print the exact exception
original_openai = structurer._process_with_openai

def debug_openai(raw_text, schema_instruction):
    try:
        print("Starting OpenAI processing...")
        res = original_openai(raw_text, schema_instruction)
        print("OpenAI finished. Result exists:", res is not None)
        return res
    except Exception as e:
        print("OpenAI EXCEPTION caught in debug wrapper:", e)
        import traceback
        traceback.print_exc()
        raise e

structurer._process_with_openai = debug_openai

print("Running process()...")
result = structurer.process(raw_text)
print("Finished process(). Result keys:", result.keys() if result else "None")
