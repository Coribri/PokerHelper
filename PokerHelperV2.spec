# Build separately; keep the original dist/StakePokerHUD recoverable.
a = Analysis(['main_hud.py'], pathex=[], binaries=[],
    datas=[('table_coords.json','.'),('helper_settings.json','.'),('templates','templates')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='PokerHelperV2',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    disable_windowed_traceback=False)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PokerHelperV2')
