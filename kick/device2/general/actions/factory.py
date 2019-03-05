from ...elektra.actions import Elektra
from ...fmc.actions import Fmc
from ...m3.actions import M3
from ...m4.actions import M4
from ...m5.actions import M5
from ...ftd5500x.actions import Ftd5500x
from ...ssp.actions import Ssp
from ...kp.actions import Kp
from ...series3.actions import Series3
from ...ep.actions import Ep
from ...chassis.actions import Chassis
from ...wm.actions import Wm

MODEL_TO_HW_MAP = {
    '63': Series3,
    '66': Fmc,
    '69': Elektra,
    '72': Elektra,
    '75': Ftd5500x,
    '76': Ssp,
    '77': Kp,
    'ep': Ep,
    'chassis': Chassis,
    '78': Wm
}


class Factory():
    @staticmethod
    def factory_by_model(model_number, args=(), kwargs={}):

        """from model number (e.g., '75') and model id (e.g., 'K', return the
        proper device class.

        When invoking function, user must specify args and kwargs to avoid
        confusion.

        :param model_number: string
        :return: the class

        """

        return MODEL_TO_HW_MAP[model_number](*args, **kwargs)

    @staticmethod
    def factory_by_name(class_name, args=(), kwargs={}):
        """from user specified device class name, return the proper device
        class.

        :param class_name: string (has to match the name of device class)
        :return: the class

        """

        return globals()[class_name](*args, **kwargs)

    @staticmethod
    def factory_by_version(device_family, version, args=(), kwargs={}):
        """users tells what family it belongs to (e.g., 'Elektra'), and version
        number (e.g., '96.1(1)47', return the proper device class.

        :param device_family: string
        :param version: string
        :return: the class

        """

        if device_family == 'Elektra':
            if version == '96.1(1)47':
                return Elektra(*args, **kwargs)
            else:
                return Elektra(*args, **kwargs)
        elif device_family == 'Fmc':
            if version.lower() == 'm3':
                return M3(*args, **kwargs)
            elif version.lower() == 'm4':
                return M4(*args, **kwargs)
            elif version.lower() == 'm5':
                return M5(*args, **kwargs)
            else:
                return Fmc(*args, **kwargs)
        else:
            raise RuntimeError('unknown device: {}'.format(device_family))
