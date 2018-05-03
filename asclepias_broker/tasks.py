# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 CERN.
#
# Asclepias Broker is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Asynchronous tasks."""

from celery import shared_task
from invenio_db import db
from marshmallow.exceptions import \
    ValidationError as MarshmallowValidationError

from .api.ingestion import update_groups, update_metadata
from .indexer import build_doc, index_documents, update_indices
from .models import Event, EventStatus, GroupRelationship, ObjectEvent, \
    PayloadType
from .schemas.loaders import RelationshipSchema


def get_or_create(model, **kwargs):
    """Get or a create a database model."""
    instance = model.query.filter_by(**kwargs)
    if instance:
        return instance
    else:
        instance = model(**kwargs)
        db.session.add(instance)
        return instance


def create_relation_object_events(event, relationship, payload_idx):
    """Create the object event models."""
    # Create the Relation entry
    rel_obj = get_or_create(
        ObjectEvent,
        event_id=event.id,
        object_uuid=relationship.id,
        payload_type=PayloadType.Relationship,
        payload_index=payload_idx)

    # Create entries for source and target
    src_obj = get_or_create(
        ObjectEvent,
        event_id=event.id,
        object_uuid=relationship.source.id,
        payload_type=PayloadType.Identifier,
        payload_index=payload_idx)
    tar_obj = get_or_create(
        ObjectEvent,
        event_id=event.id,
        object_uuid=relationship.target.id,
        payload_type=PayloadType.Identifier,
        payload_index=payload_idx)
    return rel_obj, src_obj, tar_obj


def compact_indexing_groups(groups_ids):
    """Compact the collected group IDs into minimal set of UUIDs."""
    # Compact operations
    ig_to_vg_map = {}
    id_groups_to_index = set()
    ver_groups_to_index = set()
    id_groups_to_delete = set()
    ver_groups_to_delete = set()
    for src_ig, trg_ig, mrg_ig, src_vg, trg_vg, mrg_vg in groups_ids:
        ig_to_vg_map[src_ig] = src_vg
        ig_to_vg_map[trg_ig] = trg_vg
        ig_to_vg_map[mrg_ig] = mrg_vg
        if not mrg_ig:
            id_groups_to_index |= {src_ig, trg_ig}
        else:
            id_groups_to_index.add(mrg_ig)
            id_groups_to_delete |= {src_ig, trg_ig}

        if not mrg_vg:
            ver_groups_to_index |= {src_vg, trg_vg}
        else:
            ver_groups_to_index.add(mrg_vg)
            ver_groups_to_delete |= {src_vg, trg_vg}
    id_groups_to_index -= id_groups_to_delete
    ver_groups_to_index -= ver_groups_to_delete
    return (id_groups_to_index, id_groups_to_delete, ver_groups_to_index,
            ver_groups_to_delete, ig_to_vg_map)


def _set_event_status(event_uuid, status):
    """Set the status of the Event."""
    event = Event.get(event_uuid)
    event.status = status
    db.session.commit()


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5 * 60)
def process_event(event_uuid: str, indexing_enabled=True):
    """Process the event."""
    # TODO: Should we detect and skip duplicated events?
    _set_event_status(event_uuid, EventStatus.Processing)
    try:
        event = Event.get(event_uuid)
        groups_ids = []
        with db.session.begin_nested():
            for payload_idx, payload in enumerate(event.payload):
                # TODO: marshmallow validation of all payloads
                # should be done on first event ingestion (check)
                relationship, errors = \
                    RelationshipSchema(check_existing=True).load(payload)
                # Errors should never happen as the payload is validated
                # with RelationshipSchema on the event ingestion
                if errors:
                    raise MarshmallowValidationError(errors)

                # Skip already known relationships
                # NOTE: This skips any extra metadata!
                if relationship.id:
                    continue
                db.session.add(relationship)
                # We need ORM relationship with IDs, since Event has
                # 'weak' (non-FK) relations to the objects, hence we need
                # to know the ID upfront
                relationship = relationship.fetch_or_create_id()
                create_relation_object_events(event, relationship, payload_idx)
                id_groups, ver_groups = update_groups(relationship)

                update_metadata(relationship, payload)
                groups_ids.append(
                    [str(g.id) if g else g for g in id_groups + ver_groups])
        db.session.commit()

        if indexing_enabled:
            compacted = compact_indexing_groups(groups_ids)
            update_indices(*compacted)

        _set_event_status(event_uuid, EventStatus.Done)
    except Exception as exc:
        _set_event_status(event_uuid, EventStatus.Error)
        process_event.retry(exc=exc)


def chunks(l, n, size):
    """Yield successive n-sized chunks from l."""
    for i in range(0, size, n):
        yield l[i:i + n]


@shared_task(ignore_result=True)
def reindex_all_relationships():
    """Reindex all relationship documents."""
    q = GroupRelationship.query.yield_per(1000)
    for chunk in chunks(q, 1000, q.count()):
        index_documents(map(build_doc, chunk), bulk=True)
