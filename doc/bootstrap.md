```

## GitHub Release Structure

Your `packages.zip` now contains:
```
packages.zip
├── hwss/
│   ├── __init__.py
│   └── server.py
├── hinstall/
│   ├── __init__.py
│   └── installer.py
└── hsys/
    ├── __init__.py
    └── ...
```

When extracted to `packages/`, it creates:
```
packages/
├── hwss/
├── hinstall/
└── hsys/
```

## Key Changes

1. **`PACKAGES_DIR = BASE_DIR / "packages"`** - everything goes here
2. **`sys.path.insert(0, str(PACKAGES_DIR))`** - add packages/ to Python path
3. **Extract to `PACKAGES_DIR`** instead of `BASE_DIR`

## Even Cleaner Alternative

If you want to be extra organized:
```
embedded_python/
├── python.exe
├── bootstrap.py
├── packages/
│   ├── .version
│   ├── hwss/
│   ├── hinstall/
│   └── hsys/
└── data/              ← For any runtime data
    ├── logs/
    └── config/


source directories and files
```
github/
├── hinstall/
│   ├── hinstall/
│   │   ├── __init__.py
│       └── ...
│
├── hwss/
|   ├── hwss/
│   │   ├── __init__.py
│   │   └── ...
│   ├── bootstrap.py
```

destination directories and files
```
python/
├── ...
├── bootstrap.py
├── bootstrap_helper.???
├── modules/
│   ├── hwss/
│   ├── hinstall/
│   └── hsys/    <- not included in the hbase
```

i want a python script to generate a `hbase-x.y.z.tar.gz`, that will be extracted to the destination directories
with x.y the api version stored in `hwss/hwss/__init__.py` as `__api_version__ = "0.1"`
and z the hwss version in the same file as `__version__ = "1"`





source directories and files
```
github/
├── hrelease/
│   ├── bootstrap/
│   │   ├── setup.py
│       ├── dist/
│       └── ...
│
├── hwss/
|   ├── hwss/
│   │   ├── __init__.py
│   │   └── ...
|   ├── bootstrap/
│   │   ├── bootstrap.py
│   │   ├── bootstrap_helpers.py
```

```
github/
├── hrelease/
│   ├── setup.py              # Main build configuration
│   ├── build_bootstrap.sh    # Linux/Mac build script
│   ├── build_bootstrap.bat   # Windows build script
│   ├── Makefile              # Alternative build system
│   └── dist/
│       ├── bootstrap/        # Bootstrap output
│       │   ├── bootstrap.py  # Minified
│       │   └── bootstrap_helpers.so/.pyd  # Compiled
│       └── modules/          # Modules output
│           └── hinstall/     # Cythonized hinstall
│               ├── __init__.py
│               └── *.so/.pyd
│
├── hinstall/
│   └── hinstall/
│       ├── __init__.py
│       └── ...
│
└── hwss/
    └── bootstrap/
        ├── bootstrap.py
        └── bootstrap_helpers.py
```




```
A:/
│
├── hrelease/
│   ├── dockerfile
│   ├── setup.py              # Main build configuration
│   ├── build_bootstrap.sh    # Linux/Mac build script
│   ├── build_bootstrap.bat   # Windows build script
│   └── dist/
│
├── hinstall/
│   └── hinstall/
│       ├── __init__.py
│       └── ...
│
└── hwss/
    └── bootstrap/
        ├── bootstrap.py
        └── bootstrap_helpers.py
```

