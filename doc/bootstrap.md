# Scenario

- development: deploy_dev.ps1
    * command:
    using appdata `python.exe bootstrap.py --devmode`
    * uses symlinks to modify the source code
    * when downloading a new version, do not overwrite the source but extract to `Modules_prod`, no need for a specific arg

- prod:








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



destination directories and files
```
python/
├── python.exe
├── ...
├── bootstrap.py
├── bootstrap_helpers.py
├── modules/
│   ├── hwss/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── wss.py
│   │   ├── logger.py
│   │   ├── backend_server.py
│   │   ...
│   │
│   ├── hinstall/
│   │   ├── __init__.py
│   │   ├── logger.py
│   │   ├── ext_package.py
│   │   ├── py_package.py     <- needs to import hwss/api.py
│   │   ├── ...
```


# Installation
    # Remove hbase_dir / bootstrap*:
    # if they are symlink and do_install:
    #     remove link
    #     elif not is_in_dev:
    #         remove files: they maybe be .py or .pyx or .so etc...
    # for m in modules:
    #       module_path = hbase_dir/ "modules" / m
    #       if current modules are symlink and do_install:
    #           currently in dev, remove the link because we are switching to prod
    #
    #       elif not is_in_dev:
    #           (because do not delete if we are in dev)
    #           delete the directory and its content
    #
    #       if do_install:
    #           Already in prod or switching to prod
    #           Create the module directory
    #           Extract the modules from the archive: filter by platform
    #           Also extract the .py /.pyx of this module

    # Install hbase_dir / bootstrap*:
    # if do_install:
    #     extract the bootstrap* from the archive: filter by platform
    #         Extract the modules from the archive: filter by platform
    #         Also extract the .py /.pyx of this module
    # Extract the bootstrap* and modules from the archive: filter by platform
