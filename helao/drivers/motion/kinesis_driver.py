from pylablib.devices import Thorlabs

# list devices
devices = Thorlabs.list_kinesis_devices()

# connect to MLJ150/M
stage = Thorlabs.KinesisMotor("49370234")

# get current status (position, status list, motion parameters)
stage.get_full_status()

# need to determine scaling factors and verify

# move_by
# move_to
# home