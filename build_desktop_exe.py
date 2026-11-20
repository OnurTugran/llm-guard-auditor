import ctypes
import shutil
import subprocess
import sys
from pathlib import Path
from PIL import Image

PROJECT_DIR = Path(__file__).parent.resolve()
DESKTOP_DIR = PROJECT_DIR.parent
LOGO_PNG = PROJECT_DIR / "assets" / "kali_owl_logo.png"
ICON_FILE = PROJECT_DIR / "app_icon.ico"
CS_FILE = PROJECT_DIR / "NativeLauncher.cs"
LOCAL_EXE = PROJECT_DIR / "LLMGuardAuditor.exe"
DESKTOP_EXE = DESKTOP_DIR / "LLMGuardAuditor.exe"

CS_SOURCE = f"""using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Program {{
    [STAThread]
    static void Main(string[] args) {{
        string projectDir = @"{PROJECT_DIR}";
        string pythonExe = @"{Path(sys.executable).resolve()}";
        string pythonwExe = Path.Combine(Path.GetDirectoryName(pythonExe), "pythonw.exe");
        string runner = File.Exists(pythonwExe) ? pythonwExe : pythonExe;
        string scriptPath = Path.Combine(projectDir, "launcher.py");

        if (!File.Exists(scriptPath)) {{
            MessageBox.Show("Proje klasörü bulunamadı:\\n" + scriptPath, "LLM Guard Auditor", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }}

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = runner;
        psi.Arguments = "\\"" + scriptPath + "\\"";
        psi.WorkingDirectory = projectDir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        Process.Start(psi);
    }}
}}
"""


def refresh_windows_desktop_icon(exe_path: Path) -> None:
    """Windows Masaüstü (Explorer) simge önbelleğini anında yeniler."""
    try:
        shell32 = ctypes.windll.shell32
        SHCNE_DELETE = 0x00000004
        SHCNE_CREATE = 0x00000002
        SHCNE_UPDATEITEM = 0x00002000
        SHCNE_UPDATEDIR = 0x00001000
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        SHCNF_PATHW = 0x0005
        SHCNF_FLUSH = 0x1000

        path_str = str(exe_path.resolve())
        dir_str = str(exe_path.parent.resolve())

        shell32.SHChangeNotify(SHCNE_DELETE, SHCNF_PATHW | SHCNF_FLUSH, ctypes.c_wchar_p(path_str), None)
        shell32.SHChangeNotify(SHCNE_CREATE, SHCNF_PATHW | SHCNF_FLUSH, ctypes.c_wchar_p(path_str), None)
        shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH, ctypes.c_wchar_p(path_str), None)
        shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW | SHCNF_FLUSH, ctypes.c_wchar_p(dir_str), None)
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH, None, None)
    except Exception as exc:
        print(f"Icon cache refresh warning: {exc}")


def build() -> None:
    if LOGO_PNG.exists():
        img = Image.open(LOGO_PNG).convert("RGBA")
        img.save(
            ICON_FILE,
            format="ICO",
            bitmap_format="bmp",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
        )

    CS_FILE.write_text(CS_SOURCE, encoding="utf-8")
    csc_path = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc_path.exists():
        csc_path = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

    cmd = [
        str(csc_path),
        "/nologo",
        "/target:winexe",
        f"/win32icon:{ICON_FILE}",
        f"/out:{LOCAL_EXE}",
        str(CS_FILE),
    ]
    subprocess.run(cmd, check=True)
    CS_FILE.unlink(missing_ok=True)

    # Eski masaüstü .exe dosyasını silip yenisini kopyala ve Windows Explorer simge önbelleğini zorla yenile
    if DESKTOP_EXE.exists():
        try:
            DESKTOP_EXE.unlink()
        except Exception:
            pass
    shutil.copy2(LOCAL_EXE, DESKTOP_EXE)
    refresh_windows_desktop_icon(DESKTOP_EXE)
    refresh_windows_desktop_icon(LOCAL_EXE)
    print(f"EXE created in project: {LOCAL_EXE}")
    print(f"EXE placed on Desktop:  {DESKTOP_EXE}")


if __name__ == "__main__":
    build()
