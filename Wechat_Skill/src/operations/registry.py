"""Operation Registry - decorator-based plugin registration.

Usage:
    from .base import BaseOperation
    from .registry import register_operation

    @register_operation("send_message")
    class SendMessageOperation(BaseOperation):
        ...
"""
from __future__ import annotations

from typing import Callable, Dict, Type

from .base import BaseOperation


class OperationRegistry:
    """Global registry for WeChat operations."""

    _operations: Dict[str, Type[BaseOperation]] = {}

    @classmethod
    def register(
        cls, name: str
    ) -> Callable[[Type[BaseOperation]], Type[BaseOperation]]:
        """Decorator to register an operation class.

        Args:
            name: unique operation name (used in API: {"operation": "<name>"})

        Example:
            @OperationRegistry.register("send_message")
            class SendMessageOperation(BaseOperation):
                ...
        """
        def decorator(op_class: Type[BaseOperation]) -> Type[BaseOperation]:
            if name in cls._operations:
                # allow re-registration (useful for hot reload during dev)
                pass
            cls._operations[name] = op_class
            op_class.name = name
            return op_class
        return decorator

    @classmethod
    def get(cls, name: str) -> Type[BaseOperation] | None:
        """Get an operation class by name."""
        return cls._operations.get(name)

    @classmethod
    def list_all(cls) -> list[dict]:
        """List all registered operations with their metadata."""
        return [
            {
                "name": op_class.name,
                "description": op_class.description,
                "requires_confirmation": op_class.requires_confirmation,
            }
            for op_class in cls._operations.values()
        ]

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._operations.clear()


# Convenience alias
register_operation = OperationRegistry.register
