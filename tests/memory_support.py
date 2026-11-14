# Copyright (c) 2026 justfaked. MIT: licenses/hs-decktracker-linux-MIT.txt.
# Synthetic graph adapted from justfaked/hs-decktracker-linux (MIT).
from engine import mono_memory as m
from fake_mono_memory import FakeHeap,FakeProcess
def hearthstone_heap(display: bool = True, choices=("CARD_A", "CARD_B", "CARD_C"), slots=None,
                     count_field=None, slot_fields=None, deck_slots="list") -> FakeHeap:
    """Hearthstone's draft-related objects, laid out like the real game.

    slots: optional [(card_id, copies)] where copies is the per-variant list the
    shipped layout uses, a plain int copy count, or None for a null list.
    count_field switches the m_count field between that list and a plain int.
    slot_fields limits which slot fields exist; deck_slots is "list", "null" or
    "missing" for the collection's slot container.
    """
    count_field = m.T_GENERICINST if count_field is None else count_field
    slot_fields = ("m_cardId", "m_count") if slot_fields is None else tuple(slot_fields)
    h = FakeHeap()
    choice_cls = h.cls("DraftChoice", [("m_cardID", m.T_STRING), ("m_packageCardIds", m.T_GENERICINST)])
    display_cls = h.cls("DraftDisplay", [("s_instance", m.T_CLASS, "static"), ("m_currentMode", m.T_VALUETYPE),
                                         ("m_choices", m.T_GENERICINST)])
    slot_cls = h.cls("DeckSlot", [(name, count_field if name == "m_count" else m.T_STRING) for name in slot_fields])
    deck_fields = [("ID", m.T_I8), ("<HeroCardID>k__BackingField", m.T_STRING)]
    if deck_slots != "missing":
        deck_fields.append(("m_slots", m.T_GENERICINST))
    deck_cls = h.cls("CollectionDeck", deck_fields)
    manager_cls = h.cls("DraftManager", [
        ("m_undergroundActive", m.T_BOOLEAN), ("m_currentUndergroundSlotType", m.T_VALUETYPE),
        ("m_currentSlotType", m.T_VALUETYPE), ("m_undergroundWins", m.T_I4), ("m_undergroundLosses", m.T_I4),
        ("m_wins", m.T_I4), ("m_losses", m.T_I4),
        ("m_undergroundDraftDeck", m.T_CLASS), ("m_draftDeck", m.T_CLASS)])
    info_cls = h.cls("ServiceInfo", [("<ServiceTypeName>k__BackingField", m.T_STRING),
                                     ("<Service>k__BackingField", m.T_OBJECT)])
    dict_cls = h.cls("Dictionary`2", [("_entries", m.T_SZARRAY)])
    locator_cls = h.cls("ServiceLocator", [("m_services", m.T_CLASS)])
    dependency_cls = h.cls("ServiceDependency", [("m_serviceLocator", m.T_CLASS)])
    jobs_cls = h.cls("Hearthstone.HearthstoneJobs", [("s_dependencyBuilder", m.T_GENERICINST, "static")])

    slots = [("CARD_A", [2, 0]), ("CARD_B", [0, 1])] if slots is None else list(slots)  # one golden copy
    objects = []
    for card_id, copies in slots:
        values = {}
        if "m_cardId" in slot_fields:
            values["m_cardId"] = card_id
        if "m_count" in slot_fields:
            if copies is None:
                values["m_count"] = None
            elif type(copies) is int or count_field == m.T_I4:
                values["m_count"] = sum(copies) if isinstance(copies, (list, tuple)) else copies
            else:
                values["m_count"] = h.list_of(list(copies), fmt="i")
        objects.append(h.obj(slot_cls, **values))
    deck_values = {"ID": 777, "<HeroCardID>k__BackingField": "HERO_09"}
    if deck_slots == "list":
        deck_values["m_slots"] = h.list_of(objects)
    elif deck_slots == "null":
        deck_values["m_slots"] = None
    deck = h.obj(deck_cls, **deck_values)
    manager = h.obj(manager_cls, m_undergroundActive=True, m_currentUndergroundSlotType=1,
                    m_undergroundWins=3, m_undergroundLosses=1, m_undergroundDraftDeck=deck)
    other = h.obj(info_cls, **{"<ServiceTypeName>k__BackingField": "CameraManager"})
    info = h.obj(info_cls, **{"<ServiceTypeName>k__BackingField": "DraftManager",
                              "<Service>k__BackingField": manager})
    entries = h.array("iiQQ", [(1, -1, 0, other), (0, 0, 0, 0), (2, -1, 0, info)], element_size=24)
    services = h.obj(dict_cls, _entries=entries)
    dependency = h.obj(dependency_cls, m_serviceLocator=h.obj(locator_cls, m_services=services))
    h.set_static(jobs_cls, "s_dependencyBuilder", h.list_of([dependency]))

    if display:
        options = [h.obj(choice_cls, m_cardID=c, m_packageCardIds=h.list_of(
            [h.string("CARD_Z")] if c == "CARD_C" else [])) for c in choices]
        instance = h.obj(display_cls, m_currentMode=2, m_choices=h.list_of(options))
        h.set_static(display_cls, "s_instance", instance)
    h.finish()
    return h
