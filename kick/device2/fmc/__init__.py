import datetime
import time
import logging

logger = logging.getLogger(__name__)

# following time all in seconds
SLEEP_TIME = 10
SYSTEM_START_UP_TIME = 120
TYPICAL_WAIT_UP_TO = 1200


def wait_for_fmc_webui(browser, fmc_url, page_title="Login",
                       wait_upto=TYPICAL_WAIT_UP_TO):
    start_time = datetime.datetime.now()
    current_time = datetime.datetime.now()
    while (current_time - start_time).total_seconds() < wait_upto:
        try:
            browser.get(fmc_url)
            assert browser.title == page_title
        except:
            logger.debug("Login page not ready. Sleeping {} sec.".format(
                SLEEP_TIME))
            time.sleep(SLEEP_TIME)
            current_time = datetime.datetime.now()
        else:
            logger.info("Login page ready. Sleep {} seconds for device to "
                "stablize.".format(SYSTEM_START_UP_TIME))
            # need a sleep of ~ 1 min, or else the new FMC gives eula page
            # when it isn't supposed to.
            time.sleep(SYSTEM_START_UP_TIME)
            break
    else:
        raise RuntimeError("login page tile not seen after {} seconds".format(
            wait_upto))
