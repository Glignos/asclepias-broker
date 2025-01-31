# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 CERN.
#
# Asclepias Broker is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Metadata functions."""

from datetime import datetime
from typing import List

from flask import current_app
from invenio_db import db

from ..core.models import Identifier, Relation, Relationship
from ..graph.api import get_group_from_id, get_or_create_groups
from ..graph.models import GroupRelationship, GroupType
from .models import GroupMetadata, GroupRelationshipMetadata


# TODO: When merging/splitting groups there is some merging/duplicating of
# metadata as well
def update_metadata_from_event(relationship: Relationship, payload: dict):
    """Updates the metadata of the source, target and relationship groups."""
    # Get identity groups for source and targer
    # TODO: Do something for this case?
    if relationship.relation == Relation.IsIdenticalTo:
        return
    src_group = next((id2g.group for id2g in relationship.source.id2groups
                      if id2g.group.type == GroupType.Identity), None)
    trg_group = next((id2g.group for id2g in relationship.target.id2groups
                      if id2g.group.type == GroupType.Identity), None)
    rel_group = GroupRelationship.query.filter_by(
        source=src_group, target=trg_group, relation=relationship.relation,
        type=GroupType.Identity).one_or_none()
    if src_group:
        src_metadata = src_group.data or GroupMetadata(group_id=src_group.id)
        src_metadata.update(payload['Source'])
    if trg_group:
        trg_metadata = trg_group.data or GroupMetadata(group_id=trg_group.id)
        trg_metadata.update(payload['Target'])
    if rel_group:
        rel_metadata = rel_group.data or \
            GroupRelationshipMetadata(group_relationship_id=rel_group.id)
        rel_metadata.update(
            {k: v for k, v in payload.items()
             if k in ('LinkPublicationDate', 'LinkProvider')})


def update_metadata(identifier: str, scheme: str, data: dict,
                    create_identity_events=True,
                    create_missing_groups=True,
                    providers: List[str] = None,
                    link_publication_date: str = None):
    """."""
    from ..events.api import EventAPI

    # Check if there are identity links that can be created:
    identifiers = data.get('Identifier', [])
    if create_identity_events and len(identifiers) > 1:
        providers = providers or ['unknown']
        providers = [{'Name': provider} for provider in providers]
        link_publication_date = link_publication_date or \
            datetime.now().isoformat()
        identifiers = data.get('Identifier')
        event = []
        source_identifier = identifiers[0]
        for target_identifier in identifiers[1:]:
            payload = {
                'RelationshipType': {
                    'Name': 'IsRelatedTo',
                    'SubTypeSchema': 'DataCite',
                    'SubType': 'IsIdenticalTo'
                },
                'Target': {
                    'Identifier': target_identifier,
                    'Type': {'Name': 'unknown'}
                },
                'LinkProvider': providers,
                'Source': {
                    'Identifier': source_identifier,
                    'Type': {'Name': 'unknown'}
                },
                'LinkPublicationDate': link_publication_date,
            }
            event.append(payload)
        try:
            EventAPI.handle_event(event, no_index=True, eager=True)
        except ValueError:
            current_app.logger.exception(
                'Error while processing identity event')
    try:
        id_value, scheme = identifiers[0]['ID'], identifiers[0]['IDScheme']
        id_group = get_group_from_id(id_value, scheme)
        if not id_group and create_missing_groups:
            identifier = Identifier(
                value=id_value, scheme=scheme).fetch_or_create_id()
            db.session.commit()
            id_group, _ = get_or_create_groups(identifier)
            db.session.commit()
        id_group.data.update(data)
        db.session.commit()
    except Exception:
        current_app.logger.exception('Error while updating group metadata')
