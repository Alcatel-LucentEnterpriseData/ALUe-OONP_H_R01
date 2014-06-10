#!/bin/env python
#
#  Copyright 2014 Alcatel-Lucent Enterprise.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
#  except in compliance with the License. You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software distributed under the License
#  is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
#  either express or implied. See the License for the specific language governing permissions
#  and limitations under the License.
#
#
# $File: omniswitch_db_v2.py$

# $Build: OONP_H_R01_6$

# $Date: 05/06/2014 12:10:39$

# $Author: vapoonat$

#
#

import logging
from sqlalchemy.orm import exc
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String

from neutron.common import exceptions as q_exc
from neutron.db import securitygroups_db as sg_db
from neutron.extensions import securitygroup as ext_sg
from neutron import manager

from neutron.db import models_v2
import neutron.db.api as db
from neutron.db.models_v2 import model_base

from neutron.plugins.omniswitch import omniswitch_constants as omni_const


LOG = logging.getLogger(__name__)

class OmniDB(object):

    # this is to say whether the omniswitch plug-in is used as standalone or along with ovs plug-in
    # if used independently, then it must use omni tables for vlan information.
    def __init__(self):
        self.use_omni_tables = False

    def initialize(self, sql_conn, sql_retries, interval, db_option):
        if db_option == omni_const.OMNI_TABLES:
            self.use_omni_tables = True
        elif db_option == omni_const.OVS_TABLES:
            self.use_omni_tables = False
        """
        options = {"sql_connection": "%s" % sql_conn }
        options.update({"sql_max_retries": sql_retries})
        options.update({"reconnect_interval": interval})
        options.update({"base": models_v2.model_base.BASEV2})
        db.configure_db(options)
        """
        db.configure_db()


    def get_port(self, port_id):
        session = db.get_session()
        try:
            port = session.query(models_v2.Port).filter_by(id=port_id).one()
        except exc.NoResultFound:
            port = None
        return port

    def get_port_from_device(self, port_id):
        """Get port from database"""
        LOG.debug(_("get_port_with_securitygroups() called:port_id=%s"), port_id)
        session = db.get_session()
        sg_binding_port = sg_db.SecurityGroupPortBinding.port_id

        query = session.query(models_v2.Port,
                          sg_db.SecurityGroupPortBinding.security_group_id)
        query = query.outerjoin(sg_db.SecurityGroupPortBinding,
                            models_v2.Port.id == sg_binding_port)
        query = query.filter(models_v2.Port.id == port_id)
        port_and_sgs = query.all()
        if not port_and_sgs:
            return None
        port = port_and_sgs[0][0]
        plugin = manager.NeutronManager.get_plugin()
        port_dict = plugin._make_port_dict(port)
        port_dict[ext_sg.SECURITYGROUPS] = [
            sg_id for port, sg_id in port_and_sgs if sg_id]
        port_dict['security_group_rules'] = []
        port_dict['security_group_source_groups'] = []
        port_dict['fixed_ips'] = [ip['ip_address']
                              for ip in port['fixed_ips']]
        return port_dict

    def set_port_status(self, port_id, status):
        session = db.get_session()
        try:
            port = session.query(models_v2.Port).filter_by(id=port_id).one()
            port['status'] = status
            session.merge(port)
            session.flush()
        except exc.NoResultFound:
            raise q_exc.PortNotFound(port_id=port_id)


    def get_network_binding(self, session, network_id):
        session = session or db.get_session()
        try:
            if self.use_omni_tables :
                binding = (session.query(OmniNetworkBinding).filter_by(network_id=network_id).one())
            else:
                binding = (session.query(OVSNetworkBinding).filter_by(network_id=network_id).one())
            return binding
        except exc.NoResultFound:
            return

    def add_network_binding(self, session, network_id, network_type,
                                          physical_network, segmentation_id):
        with session.begin(subtransactions=True):
            if self.use_omni_tables :
                binding = OmniNetworkBinding(network_id, network_type,
                                               physical_network,
                                               segmentation_id)
                session.add(binding)
            else: 
                LOG.INFO("add_network_binding: Should not have come here when OVS plug-in is used!!!")


    def sync_vlan_allocations(self, network_vlan_ranges):
        """Synchronize vlan_allocations table with configured VLAN ranges"""

        session = db.get_session()
        with session.begin():
            # get existing allocations for all physical networks
            allocations = dict()
            allocs = (session.query(OmniVlanAllocation).all())
            for alloc in allocs:
                if alloc.physical_network not in allocations:
                    allocations[alloc.physical_network] = set()
                allocations[alloc.physical_network].add(alloc)

            # process vlan ranges for each configured physical network
            for physical_network, vlan_ranges in network_vlan_ranges.iteritems():
                # determine current configured allocatable vlans for this
                # physical network
                vlan_ids = set()
                for vlan_range in vlan_ranges:
                    vlan_ids |= set(xrange(vlan_range[0], vlan_range[1] + 1))

                # remove from table unallocated vlans not currently allocatable
                if physical_network in allocations:
                    for alloc in allocations[physical_network]:
                        try:
                            # see if vlan is allocatable
                            vlan_ids.remove(alloc.vlan_id)
                        except KeyError:
                            # it's not allocatable, so check if its allocated
                            if not alloc.allocated:
                                # it's not, so remove it from table
                                LOG.debug("removing vlan %s on physical network "
                                          "%s from pool" %
                                          (alloc.vlan_id, physical_network))
                                session.delete(alloc)
                    del allocations[physical_network]

                # add missing allocatable vlans to table
                for vlan_id in sorted(vlan_ids):
                    alloc = OmniVlanAllocation(physical_network, vlan_id)
                    session.add(alloc)

            # remove from table unallocated vlans for any unconfigured physical
            # networks
            for allocs in allocations.itervalues():
                for alloc in allocs:
                    if not alloc.allocated:
                        LOG.debug("removing vlan %s on physical network %s"
                                  " from pool" %
                                  (alloc.vlan_id, physical_network))
                        session.delete(alloc)


    def get_vlan_allocation(self, physical_network, vlan_id):
        session = db.get_session()
        try:
            alloc = (session.query(OmniVlanAllocation).
                             filter_by(physical_network=physical_network, 
                             vlan_id=vlan_id).one())
            return alloc
        except exc.NoResultFound:
            return


    def reserve_vlan(self, session):
        with session.begin(subtransactions=True):
            alloc = (session.query(OmniVlanAllocation).
                     filter_by(allocated=False).
                     first())
            if alloc:
                LOG.debug("reserving vlan %s on physical network %s from pool" %
                          (alloc.vlan_id, alloc.physical_network))
                alloc.allocated = True
                return (alloc.physical_network, alloc.vlan_id)
        raise q_exc.NoNetworkAvailable()


    def release_vlan(self, session, physical_network, vlan_id, network_vlan_ranges):
        with session.begin(subtransactions=True):
            try:
                alloc = (session.query(OmniVlanAllocation).
                         filter_by(physical_network=physical_network,
                                   vlan_id=vlan_id).one())
                alloc.allocated = False
                inside = False
                for vlan_range in network_vlan_ranges.get(physical_network, []):
                    if vlan_id >= vlan_range[0] and vlan_id <= vlan_range[1]:
                        inside = True
                        break
                if not inside:
                    session.delete(alloc)
                LOG.debug("releasing vlan %s on physical network %s %s pool" %
                          (vlan_id, physical_network,
                           inside and "to" or "outside"))
            except exc.NoResultFound:
                LOG.warning("vlan_id %s on physical network %s not found" %
                            (vlan_id, physical_network))


class OmniNetworkBinding(model_base.BASEV2):
    """Represents binding of virtual network to physical realization"""
    __tablename__ = 'omni_network_bindings'

    network_id = Column(String(36),
                        ForeignKey('networks.id', ondelete="CASCADE"),
                        primary_key=True)
    # 'gre', 'vlan', 'flat', 'local'
    network_type = Column(String(32), nullable=False)
    physical_network = Column(String(64))
    segmentation_id = Column(Integer)  # tunnel_id or vlan_id

    def __init__(self, network_id, network_type, physical_network,
                 segmentation_id):
        self.network_id = network_id
        self.network_type = network_type
        self.physical_network = physical_network
        self.segmentation_id = segmentation_id

    def __repr__(self):
        return "<OmniNetworkBinding(%s,%s,%s,%d)>" % (self.network_id,
                                                  self.network_type,
                                                  self.physical_network,
                                                  self.segmentation_id)

class OVSNetworkBinding(model_base.BASEV2):
    """Represents binding of virtual network to physical realization"""
    __tablename__ = 'ovs_network_bindings'
    __table_args__ = {'extend_existing': True}

    network_id = Column(String(36),
                        ForeignKey('networks.id', ondelete="CASCADE"),
                        primary_key=True)
    # 'gre', 'vlan', 'flat', 'local'
    network_type = Column(String(32), nullable=False)
    physical_network = Column(String(64))
    segmentation_id = Column(Integer)  # tunnel_id or vlan_id

    def __init__(self, network_id, network_type, physical_network,
                 segmentation_id):
        self.network_id = network_id
        self.network_type = network_type
        self.physical_network = physical_network
        self.segmentation_id = segmentation_id

    def __repr__(self):
        return "<OVSNetworkBinding(%s,%s,%s,%d)>" % (self.network_id,
                                                  self.network_type,
                                                  self.physical_network,
                                                  self.segmentation_id)

class OmniVlanAllocation(model_base.BASEV2):
    """Represents allocation state of vlan_id on physical network"""
    __tablename__ = 'omni_vlan_allocations'

    physical_network = Column(String(64), nullable=False, primary_key=True)
    vlan_id = Column(Integer, nullable=False, primary_key=True,
                     autoincrement=False)
    allocated = Column(Boolean, nullable=False)

    def __init__(self, physical_network, vlan_id):
        self.physical_network = physical_network
        self.vlan_id = vlan_id
        self.allocated = False

    def __repr__(self):
        return "<OmniVlanAllocation(%s,%d,%s)>" % (self.physical_network,
                                               self.vlan_id, self.allocated)

