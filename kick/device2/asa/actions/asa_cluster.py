"""Copyright (c) 2017 Cisco Systems, Inc.
Name:
    asa_cluster.py
Usage:
    Submodule for Legacy ASA Cluster.
Author:
    raywa
"""

import re
import time
from .constants import ASAClusterStates, AsaSmStates


class AsaCluster():
    """Class ASA Cluster
    """
    def __init__(self, asa_instances, clu_group_name):
        """Initializer of AsaCluster

        :param asa_instances: list of connection instances of cluster members,
            each of which should be created by class AsaLine
        :param clu_group_name: cluster group name
        :return: None

        """

        self.clu_group_name = clu_group_name
        self.asa_instances = asa_instances
        self.master = None

    def pick_up_master(self):
        """Pick up the master unit in the cluster

        :return: connection instance of the master unit

        """

        for unit in self.asa_instances:
            dump = unit.expect_prompt()
            clu_info = unit.execute('show cluster info')
            # pylint: disable=anomalous-backslash-in-string
            match = re.search('This is .* in state (\S+)', clu_info)
            if match and match.group(1) == ASAClusterStates.MASTER.value:
                self.master = unit
                return unit

        self.master = None
        return None

    def make_master(self, unit):
        """Force a particular unit to be master

        :param unit: connection instance of the unit to be new master.
        :return: None

        """

        self.enable_unit(unit)
        if unit != self.master:
            unit.go_to(AsaSmStates.CONFIG_STATE.value)
            unit.spawn_id.sendline('cluster master')
            unit.spawn_id.expect('Cluster unit .* transitioned from .* to {}'.\
                format(ASAClusterStates.MASTER.value))
            dump = unit.expect_prompt()
            self.master = unit

    @staticmethod
    def is_unit_ready(unit):
        """Check if a unit is ready in cluster.
        A cluster member's ready state should be either MASTER or SLAVE

        :param unit: connection instance of the unit to be checked
        :return: True | False

        """

        dump = unit.expect_prompt()
        output = unit.execute('show cluster info')
        if 'not enabled' in output:
            # unit.logger.info('Clustering is not enabled in this unit')
            return False

        clu_info = output[: re.search('Other members', output).start()]
        # pylint: disable=anomalous-backslash-in-string
        match = re.search('in state (\S+)', clu_info)
        if match:
            state = match.group(1)
            return state == ASAClusterStates.MASTER.value or state == ASAClusterStates.SLAVE.value
        else:
            # unit.logger.info('Did not find cluster state info on this unit')
            return False

    def wait_until_all_units_ready(self, timeout=120):
        """Wait until all units ready in cluster

        :param timeout: total wait time
        :return: True | False

        """

        current_time = start_time = time.time()
        while current_time - start_time <= timeout:
            units_ready = True
            for unit in self.asa_instances:
                units_ready = units_ready and self.is_unit_ready(unit)
            if units_ready:
                return True
            time.sleep(10)
            current_time = time.time()
        return False

    def disable_unit(self, unit):
        """Disable a unit in cluster
        If unit to be disabled is master, return new master

        :param unit: connection instance of the unit to be disabled
        :return: If unit to be disabled is master, return new master

        """

        dump = unit.expect_prompt()
        unit.config('cluster group %s' % self.clu_group_name)
        unit.spawn_id.sendline('no enable')

        prompt = unit.sm.get_state(unit.sm.current_state).pattern
        output = unit.spawn_id.expect(prompt).last_match.string

        # pylint: disable=anomalous-backslash-in-string
        match = re.search('Cluster unit .* transitioned from (\S+) to %s' \
            % ASAClusterStates.DISABLED.value, output)
        if match and match.group(1) == ASAClusterStates.MASTER.value:
            return self.pick_up_master()

    def enable_unit(self, unit, timeout=120):
        """Enable a unit that is not currently in cluster

        :param unit: connection instance of the unit to be added.
        :param timeout: duration to wait for the unit to be in cluster
        :return: return the unit if it becomes master

        """

        dump = unit.expect_prompt()
        clu_info = unit.execute('show cluster info')
        if 'not enabled' in clu_info:
            unit.config('cluster group %s' % self.clu_group_name)
            unit.spawn_id.sendline('enable')
            current_timeout = unit.spawn_id.timeout
            unit.spawn_id.timeout = timeout
            output = unit.spawn_id.expect('Cluster unit .* transitioned from %s to .*' \
                % ASAClusterStates.DISABLED.value).last_match.string
            unit.spawn_id.timeout = current_timeout
            if re.search('from %s to %s' % \
                (ASAClusterStates.DISABLED.value, ASAClusterStates.MASTER.value), output):
                return self.pick_up_master()
        dump = unit.expect_prompt()

    def get_unit_by_name(self, name):
        """ Get unit ssh handle via its name

        Many time, scripts need to extract unit name from "cluster exec show ..."
        commands, and then execute cluster operations (exit/join) via its ssh handle.

        For example, unit 'unit-1-1' can be identified from the below output and
        then foreced to exit and rejoin cluster. Thus we need to get its corresponding
        handle from its name and pass it to disable_unit(unit) and enable_unit(unit).

        cluster exec show conn
        unit-1-1(LOCAL):******************************************************
        33 in use, 40 most used
        Cluster:
                fwd connections: 0 in use, 0 most used
                dir connections: 0 in use, 0 most used
                centralized connections: 0 in use, 9 most used
                VPN redirect connections: 0 in use, 0 most used

        UDP outside  10.2.0.10:2152 inside  10.1.0.10:0, idle 0:00:00, bytes 0, flags ji
        UDP outside  10.2.0.10:0 inside  10.1.0.10:2152, idle 0:00:00, bytes 0, flags ji


        unit-3-1:*************************************************************
        17 in use, 29 most used
        Cluster:
                fwd connections: 0 in use, 0 most used
                dir connections: 1 in use, 1 most used
                centralized connections: 0 in use, 12 most used
                VPN redirect connections: 0 in use, 0 most used

        UDP outside  10.2.0.10:2152 inside  10.1.0.10:0, idle 0:00:01, bytes 0, flags ji
        UDP outside  10.2.0.10:0 inside  10.1.0.10:2152, idle 0:00:01, bytes 0, flags ji
        UDP outside  10.2.0.10:2123 inside  10.1.0.10:2123, idle 0:00:01, bytes 0, flags -Y


        unit-2-1:*************************************************************
        18 in use, 29 most used
        Cluster:
                fwd connections: 0 in use, 0 most used
                dir connections: 0 in use, 0 most used
                centralized connections: 0 in use, 12 most used
                VPN redirect connections: 0 in use, 0 most used

        UDP outside  10.2.0.10:2152 inside  10.1.0.10:0, idle 0:00:01, bytes 0, flags ji
        UDP outside  10.2.0.10:2123 inside  10.1.0.10:2123, idle 0:00:01, bytes 1824, flags J
        UDP outside  10.2.0.10:0 inside  10.1.0.10:2152, idle 0:00:01, bytes 0, flags ji

        :param name: unit name, eg 'unit-1-1'
        :return:
            unit ssh handle if found
            None otherwise
        """
        for unit in self.asa_instances:
            dump = unit.expect_prompt()
            output = unit.execute('show cluster info')
            found = re.search('This is .%s.' % name, output)
            if found:
                return unit
        else:
            return None
