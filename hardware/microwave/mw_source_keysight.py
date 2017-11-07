# -*- coding: utf-8 -*-

"""
This file contains the Qudi hardware file to control Keysight microwave device.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Parts of this file were developed from a PI3diamond module which is
Copyright (C) 2009 Helmut Rathgen <helmut.rathgen@gmail.com>

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

import visa
import numpy as np
import time

from core.module import Base
from interface.microwave_interface import MicrowaveInterface
from interface.microwave_interface import MicrowaveLimits
from interface.microwave_interface import MicrowaveMode
from interface.microwave_interface import TriggerEdge


class MicrowaveKeysight(Base, MicrowaveInterface):
    """ This is the Interface class to define the controls for the simple
        microwave hardware.
    """

    _modclass = 'MicrowaveKeysight'
    _modtype = 'hardware'

    def on_activate(self):
        """ Initialisation performed during activation of the module."""
        # checking for the right configuration
        config = self.getConfiguration()
        # agilent mw source has USB connection, therefore configuration checks for USB address
        if 'address' in config.keys():
            self._address = config['address']
        else:
            self.log.error(
                'This is MWKEYSIGHT: did not find >>address<< in '
                'configuration.')

        if 'timeout' in config.keys():
            self._timeout = int(config['timeout'])
        else:
            self._timeout = 10 * 1000
            self.log.error(
                'This is MWKEYSIGHT: did not find >>timeout<< in '
                'configuration. I will set it to 10 seconds.')

        if 'trigger' in config.keys():
            self._trigger = config['trigger']
        else:
            self._trigger = 'TRIG1'
            self.log.error(
                'This is MWKEYSIGHT: did not find >>trigger<< in '
                'configuration. Setting to TRIG1'
            )

        # trying to load the visa connection to the module
        self.rm = visa.ResourceManager()
        self.log.info('Opening connection to Keysight {}'.format(self._address))
        self._connection = self.rm.open_resource(resource_name=self._address,
                                                 timeout=self._timeout)

        self.model = self._connection.query('*IDN?').split(',')[1]
        self.log.info('MWKEYSIGHT initialised and connected to hardware. {}'.format(self.model))

    def on_deactivate(self, e):
        """ Deinitialisation performed during deactivation of the module.

        @param object e: Event class object from Fysom. A more detailed
                         explanation can be found in method activation.
        """

        self._connection.close()
        self.rm.close()

    def get_limits(self):
        limits = MicrowaveLimits()
        limits.supported_modes = ('CW', 'LIST', 'SWEEP')

        limits.min_frequency = 300e3
        limits.max_frequency = 6.4e9

        limits.min_power = -144
        limits.max_power = 10

        limits.list_minstep = 0.1
        limits.list_maxstep = 6.4e9
        limits.list_maxentries = 4000

        limits.sweep_minstep = 0.1
        limits.sweep_maxstep = 6.4e9
        limits.sweep_maxentries = 10001

        if str.lstrip(self.model) == 'N5172B':
            limits.min_frequency = 9e3
            limits.max_frequency = 6.0e9
            limits.min_power = -127
            limits.max_power = 9
            limits.list_maxentries = 3201
            limits.sweep_maxentries = 65535
        else:
            self.log.warning('Model string unknown, hardware limits may be wrong.')
        limits.list_maxstep = limits.max_frequency
        limits.sweep_maxstep = limits.max_frequency

        return limits

    def on(self):
        """ Switches on any preconfigured microwave output.

        @return int: error code (0:OK, -1:error)
        """

        self._connection.write(':OUTP:STAT ON')

        return 0

    def off(self):
        """ Switches off any microwave output.

        @return int: error code (0:OK, -1:error)
        """

        self._connection.write(':OUTP:STAT OFF')

        return 0

    def get_power(self):
        """ Gets the microwave output power.

        @return float: the power set at the device in dBm
        """
        return float(self._connection.query(':POWER?'))

    def set_power(self, power=0.):
        """ Sets the microwave output power.

        @param float power: the power (in dBm) set for this device

        @return int: error code (0:OK, -1:error)
        """
        if power is not None:
            self._connection.write(':POWER {0:f}'.format(power))
            return 0
        else:
            return -1

    def get_frequency(self):
        """
        Gets the frequency of the microwave output.
        Returns single float value if the device is in cw mode.
        Returns list like [start, stop, step] if the device is in sweep mode.
        Returns list of frequencies if the device is in list mode.

        @return [float, list]: frequency(s) currently set for this device in Hz
        """
        mode, is_running = self.get_status()
        if 'cw' in mode:
            return float(self._connection.query(':FREQ?'))
        elif 'sweep' in mode:
            start = float(self._connection.query(':FREQ:STAR?'))
            stop = float(self._connection.query(':FREQ:STOP?'))
            step = float(self._connection.query(':SWE:FREQ:STEP?'))
            return [start+step, stop, step]
        elif 'list' in mode:
            f = float(self._connection.query(':LIST:FREQ?'))
            self.log.error('Getting frequency list in list sweep mode is not implemented')
            return [0.0, 0.0, 0.0]

    def set_frequency(self, freq=None):
        """ Sets the frequency of the microwave output.

        @param float freq: the frequency (in Hz) set for this device

        @return int: error code (0:OK, -1:error)
        """
        if freq is not None:
            self._connection.write(':FREQ {0:e} Hz'.format(freq))
            return 0
        else:
            return -1

    def get_status(self):
        """
        Gets the current status of the MW source, i.e. the mode (cw, list or sweep) and
        the output state (stopped, running)

        @return str, bool: mode ['cw', 'list', 'sweep'], is_running [True, False]
        """
        is_running = bool(int(float(self._connection.query('OUTP:STAT?'))))
        mode = self._connection.query(':FREQ:MODE?').strip('\n').lower()
        list_type = self._connection.query(':LIST:TYPE?').strip('\n').lower()
        if mode == 'list':
            if list_type == 'list':
                mode = 'list'
            else:
                mode = 'sweep'
        else:
            mode = 'cw'
        return mode, is_running

    def cw_on(self):
        """ Switches on any preconfigured microwave output.

        @return int: error code (0:OK, -1:error)
        """
        mode, is_running = self.get_status()
        if is_running:
            if mode == 'cw':
                return 0
            else:
                self.off()

        if mode != 'cw':
            self._connection.write(':FREQ:MODE CW')

        self._connection.write(':OUTP:STAT ON')
        dummy, is_running = self.get_status()
        while not is_running:
            time.sleep(0.2)
            dummy, is_running = self.get_status()
        return 0

    def set_cw(self, freq=None, power=None, useinterleave=None):
        """ Sets the MW mode to cw and additionally frequency and power
        #For agilent device there is no CW mode, so just do nothing

        @param float freq: frequency to set in Hz
        @param float power: power to set in dBm
        @param bool useinterleave: If this mode exists you can choose it.

        @return float, float, str: current frequency in Hz, current power in dBm, current mode

        Interleave option is used for arbitrary waveform generator devices.
        """

        if freq is not None:
            self.set_frequency(freq)
        else:
            self.log.warning('Frequency is none')
        if power is not None:
            self.set_power(power)
        else:
            self.log.warning('Power is none')

        mode, dummy = self.get_status()
        actual_freq = self.get_frequency()
        actual_power = self.get_power()
        return actual_freq, actual_power, mode

    def set_list(self, freq=None, power=None):
        """
        @param list freq: list of frequencies in Hz
        @param float power: MW power of the frequency list in dBm

        """
#        if self.set_cw(freq[0],power) != 0:
#            error = -1

        #self._usb_connection.write(':SWE:RF:STAT ON')

        # put all frequencies into a string, first element is doubled
        # so there are n+1 list entries for scanning n frequencies
        # due to counter/trigger issues
        freqstring = ' {0:f},'.format(freq[0])
        for f in freq[:-1]:
            freqstring += ' {0:f},'.format(f)
        freqstring += ' {0:f}'.format(freq[-1])

        freqcommand = ':LIST:FREQ' + freqstring

        self._connection.write(':FREQ:MODE LIST')
        self._connection.write(':LIST:TYPE LIST')
        self._connection.write(':LIST:DWEL 10 ms')
        self._connection.write(freqcommand)
        self._connection.write(':POWER {0:f}'.format(power))

        self._connection.write(':OUTP:STAT ON')

        return 0

    def reset_listpos(self):
        """ Reset of MW List Mode position to start from first given frequency

        @return int: error code (0:OK, -1:error)
        """
        self._connection.write(':LIST:MAN 1')
        self._connection.write('*WAI')
        return 0

    def reset_sweeppos(self):
        """
        Reset of MW sweep mode position to start (start frequency)

        @return int: error code (0:OK, -1:error)
        """
        self._connection.write(':ABORT')
        return 0

    def set_sweep(self, start, stop, step, power):
        """
        @param start:
        @param stop:
        @param step:
        @param power:
        @return:
        """
        n = int(((stop - start) / step) + 1)

        self._connection.write(':LIST:TYPE STEP')
        self._connection.write(':FREQ:MODE LIST')
        self._connection.write(':FREQ:STAR {0:e} Hz'.format(start))
        self._connection.write(':FREQ:STOP {0:e} Hz'.format(stop))
        self._connection.write(':SWE:FREQ:STEP:LIN {0:e} Hz'.format(step))
        self._connection.write(':SWE:DWEL 10 ms')

        if power is not None:
            self.set_power(power)

        power = self.get_power()

        n = int(np.round(float(self._connection.query(':SWE:POIN?\n'))))
        self.on()

        return start, stop, step, power, 'sweep'

    def reset_sweep(self):
        """ Reset of MW List Mode position to start from first given frequency

        @return int: error code (0:OK, -1:error)
        """
        self._connection.write(':LIST:MAN 1')
        self._connection.write('*WAI')
        return 0

    def sweep_on(self):
        """ Switches on the list mode.

        @return int: error code (1: ready, 0:not ready, -1:error)
        """
        print('sweep on')
        self._connection.write(':OUTP:STAT ON')

        return 1

    def list_on(self):
        """ Switches on the list mode.

        @return int: error code (1: ready, 0:not ready, -1:error)
        """
        self._connection.write(':OUTP:STAT ON')

        return 1

    def set_ext_trigger(self, pol=TriggerEdge.RISING):
        """ Set the external trigger for this device with proper polarization.

        @param str source: channel name, where external trigger is expected.
        @param str pol: polarisation of the trigger (basically rising edge or
                        falling edge)

        @return int: error code (0:OK, -1:error)
        """
        if pol == TriggerEdge.RISING:
            edge = 'POS'
        elif pol == TriggerEdge.FALLING:
            edge = 'NEG'
        else:
            return -1
        try:
            self._connection.write(':LIST:TRIG:EXT:SOUR {0}'.format(self._trigger))
            self._connection.write(':LIST:TRIG:SLOP {0}'.format(edge))

        except:
            return -1
        return 0