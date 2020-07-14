import logging
import re

import time
from munch import munchify as bunchify

logger = logging.getLogger(__name__)


def create_dict(data):
    d = bunchify({})
    for line in data.split('\r\n'):
        if ':' in line:
            line = line.split(':')
            if not (line[0].strip() is '' or line[1].strip() is ''):
                if len(line) > 2:
                    d[line[0].strip()] = ':'.join(line[1:]).strip()
                else:
                    d[line[0].strip()] = line[-1].strip()
    return d


def scope(handle, path, conn='console'):
    if path == 'top':
        handle.execute('top')
        handle.execute('')
    else:
        for sc in path.split('/'):
            if conn == 'console':
                handle.execute('scope %s' % sc)
                handle.execute('')


def poll(handle, command, expect, scope='', max_retry=1, interval=1, flags=re.DOTALL):
    if scope != '':
        scope(handle, scope)

    cnt = 0
    while cnt < max_retry:
        cnt += 1
        logger.info("Looking for '%s' in '%s' output" % (expect, command))
        output = handle.execute(command)
        output = re.sub('(\r|\n| )+', ' ', output)
        m = re.search(re.compile(expect, flags), output)
        if not m:
            if cnt == max_retry:
                duration = cnt * interval
                logger.info("'%s' is not found in the output within %s seconds" \
                            % (expect, duration))
                if scope != '':
                    scope(handle, 'top')
                return False
            else:
                time.sleep(interval)
        else:
            duration = cnt * interval
            logger.info("'%s' is found within %s seconds" % (m.group(0), duration))
            if scope != '':
                scope(handle, 'top')
            return True
