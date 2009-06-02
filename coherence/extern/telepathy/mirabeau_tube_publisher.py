
import telepathy

from coherence.extern.telepathy import tube
from coherence.dbus_constants import BUS_NAME, OBJECT_PATH

class MirabeauTubePublisher(tube.TubePublisher):
    def __init__(self, connection, chatroom, tubes_to_offer, application,
                 allowed_devices):
        super(MirabeauTubePublisher, self).__init__(connection, chatroom,
                                                    tubes_to_offer)
        self.coherence = application
        self.allowed_devices = allowed_devices

    def tube_opened(self, id):
        super(MirabeauTubePublisher, self).tube_opened(id)
        self.coherence.dbus.add_to_connection(self.tube_conn, OBJECT_PATH)
        for device in self.coherence.dbus.devices.values():
            if self.allowed_devices != None and device.uuid not in self.allowed_devices:
                return
            self._register_device(device)
        self.coherence.dbus.bus.add_signal_receiver(self._media_server_found,
                                                    "UPnP_ControlPoint_MediaServer_detected")
        self.coherence.dbus.bus.add_signal_receiver(self._media_server_removed,
                                                    "UPnP_ControlPoint_MediaServer_removed")

    def _media_server_found(self, infos, udn):
        uuid = udn[5:]
        for device in self.coherence.dbus.devices.values():
            if device.uuid == uuid:
                if self.allowed_devices != None and device.uuid not in self.allowed_devices:
                    return
                self._register_device(device)
                return

    def _register_device(self, device):
        name = '%s (%s)' % (device.get_friendly_name(),
                            ':'.join(device.get_device_type().split(':')[3:5]))
        print "device found: %s" % name
        try:
            device.add_to_connection(self.tube_conn, device.path())
            print "device add_to_connection: %s" % name
        except Exception, exc:
            # XXX: remove this when Pontoon doesn't store duplicates anymore
            pass
        else:
            for service in device.services:
                service.add_to_connection(self.tube_conn, service.path)

    def _media_server_removed(self, udn):
        for device in self.coherence.dbus.devices.values():
            if udn == device.device.get_id():
                print "remove", device.get_friendly_name()
                #if self.allowed_devices != None and device.uuid not in self.allowed_devices:
                #    continue
                try:
                    device.remove_from_connection(self.tube_conn, device.path())
                    print "remove_from_connection: %s" % device.get_friendly_name()
                except:
                    # XXX: remove this when Pontoon doesn't store duplicates anymore
                    continue
                else:
                    for service in device.services:
                        service.remove_from_connection(self.tube_conn, service.path)
                    break
