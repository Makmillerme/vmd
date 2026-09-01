#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модулі управління Trello.
Розділено на підмодулі для кращої організації.
"""

from .menu import show_trello_menu, TrelloMenu
from .sync import sync_vehicles_to_trello
from .cards import show_trello_stats, verify_trello_links, add_trello_cards_by_vins
from .labels import (
    show_trello_labels_menu,
    create_trello_labels,
    show_trello_labels_list,
    check_vehicle_type_duplicates,
    fix_vehicle_type_case,
    fix_vehicle_type_typos_in_db,
    update_label_colors_to_sky,
    remove_all_labels_from_cards,
    sync_labels_on_all_cards
)
from .custom_fields import sync_custom_fields_for_all_cards, check_and_fix_custom_fields_for_all_cards

__all__ = [
    'show_trello_menu',
    'TrelloMenu',
    'sync_vehicles_to_trello',
    'show_trello_stats',
    'verify_trello_links',
    'add_trello_cards_by_vins',
    'show_trello_labels_menu',
    'create_trello_labels',
    'show_trello_labels_list',
    'check_vehicle_type_duplicates',
    'fix_vehicle_type_case',
    'fix_vehicle_type_typos_in_db',
    'update_label_colors_to_sky',
    'remove_all_labels_from_cards',
    'sync_labels_on_all_cards',
    'sync_custom_fields_for_all_cards',
    'check_and_fix_custom_fields_for_all_cards',
]




