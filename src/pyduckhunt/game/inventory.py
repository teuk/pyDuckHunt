"""Immutable inventory operations over stable item identifiers."""

from __future__ import annotations

from dataclasses import replace

from pyduckhunt.game.model import InventoryStack, PlayerState


def item_quantity(player: PlayerState, key: str) -> int:
    return next(
        (stack.quantity for stack in player.inventory if stack.key == key),
        0,
    )


def add_item(player: PlayerState, key: str, quantity: int = 1) -> PlayerState:
    if type(quantity) is not int or quantity < 1:
        raise ValueError("added quantity must be a positive integer")
    existing = item_quantity(player, key)
    replacement = InventoryStack(key, existing + quantity)
    retained = tuple(stack for stack in player.inventory if stack.key != key)
    inventory = tuple(sorted((*retained, replacement), key=lambda stack: stack.key))
    return replace(player, inventory=inventory)


def remove_item(player: PlayerState, key: str, quantity: int = 1) -> PlayerState:
    if type(quantity) is not int or quantity < 1:
        raise ValueError("removed quantity must be a positive integer")
    existing = item_quantity(player, key)
    if quantity > existing:
        raise ValueError("insufficient item quantity")
    retained = tuple(stack for stack in player.inventory if stack.key != key)
    if existing > quantity:
        retained = (*retained, InventoryStack(key, existing - quantity))
    inventory = tuple(sorted(retained, key=lambda stack: stack.key))
    return replace(player, inventory=inventory)
