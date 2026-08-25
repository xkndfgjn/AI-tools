"""Operation Layer - pluggable WeChat operations.

Each operation is a class inheriting BaseOperation, registered via @register_operation.
This __init__ auto-imports all modules in this package so registrations execute.

To add a new operation:
1. Create a new file in this directory (e.g., post_moment.py)
2. Inherit BaseOperation, implement execute()
3. Decorate with @register_operation("operation_name")
4. It will be auto-discovered by this __init__.py
"""
import importlib
import pkgutil

# Auto-import all modules in this package to trigger @register_operation decorators
for _, module_name, _ in pkgutil.iter_modules(__path__):
    if module_name == "__init__":
        continue
    importlib.import_module(f"{__name__}.{module_name}")
