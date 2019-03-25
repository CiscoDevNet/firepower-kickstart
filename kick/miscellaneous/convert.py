''' convert bytes to string and string to bytes '''


def string_to_bytes(string):
    ''' convert a string to bytes '''
    return bytes(string, 'utf-8')


def bytes_to_string(byt):
    ''' convert bytes to string '''
    return byt.decode('utf-8')
