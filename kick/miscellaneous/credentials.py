import configparser
import os

config = configparser.ConfigParser()
try:
    kick_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config.read(os.path.join(kick_path, 'config.ini'))
except:
    pass

DEFAULT = 'DEFAULT'
USERNAME = 'username'
PASSWORD = 'password'
EN_PASSWORD = 'en_password'

def get_username(user):
    """
    Gets the username from config file if present

    :param user: username given by user
            if not given, defaulted to ['myusername']
    :return: username
    """
    if USERNAME in config[DEFAULT]:
        return config[DEFAULT][USERNAME]
    else:
        return user


def get_password(pwd):
    """
    Gets the password from config file if present

    :param pwd: password given by user
            if not given, defaulted to ['mypassword']
    :return: password
    """
    if PASSWORD in config[DEFAULT]:
        return config[DEFAULT][PASSWORD]
    else:
        return pwd


def get_en_password(en_password):
    """
    Gets the en_password from config file if present

    :param en_password: en_password given by user
            if not given, defaulted to ['myenpassword']
    :return: en_password
    """
    if EN_PASSWORD in config[DEFAULT]:
        return config[DEFAULT][EN_PASSWORD]
    else:
        return en_password


class KickConsts(object):
    DEFAULT_PASSWORD = 'Admin123'
    DUMMY_PASSWORD = 'Admin123!'
