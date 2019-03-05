"""This is nothing but a place holder, to save instance-specific variables.

For this to work, the __init__() of the class has to be written as below:
 1. Initialize SspConstants.hostname, login_username and login_password
 2. Create the state machine.

In step 2 above, the state machine is written with the assumption that
SspConstants is properly initialized. That's why the order in __init__()
above can not be reversed.

"""

class SspConstants:
    pass