# sound_light_pb2.py — Nanit Sound + Light protobuf schema
#
# WHAT THIS FILE IS
# -----------------
# This is a compiled Python protobuf module for the Nanit Sound + Light
# (sound machine / night light) device. It defines the message types used
# to communicate with that device over its WebSocket connection.
#
# It is NOT related to the Nanit camera protobuf (which lives in aionanit).
# The camera and the sound machine use completely different protocols on
# completely different WebSocket endpoints.
#
# WHERE IT CAME FROM
# ------------------
# This schema was reverse-engineered from the Nanit Android APK by
# com6056 and published at:
#   https://github.com/com6056/nanit-sound-light  (MIT License)
#
# The original .proto definition is:
#
#   message Message {
#     optional Request  request  = 1;
#     optional Response response = 2;
#     optional bytes    backend  = 3;
#   }
#   message Request {
#     optional int32       id          = 1;
#     optional string      sessionId   = 200;  // varint field 200
#     optional GetSettings getSettings = 5;
#     optional Settings    settings    = 6;
#     optional Status      status      = 10;
#   }
#   message Response {
#     optional int32    requestId     = 1;
#     optional int32    statusCode    = 2;
#     optional string   statusMessage = 3;
#     optional Settings settings      = 4;
#     optional Status   status        = 6;
#   }
#   message GetSettings {
#     optional bool all         = 1;
#     optional bool savedSounds = 7;
#     optional bool temperature = 8;
#     optional bool humidity    = 9;
#   }
#   message Settings {
#     optional float     brightness  = 1;
#     optional Color     color       = 2;
#     optional float     volume      = 3;  // 0.0–1.0
#     optional Sound     sound       = 4;
#     optional bool      isOn        = 5;
#     optional SoundList soundList   = 6;
#     optional float     temperature = 7;
#     optional float     humidity    = 8;
#   }
#   message Color {
#     optional bool  noColor    = 1;
#     optional float hue        = 2;
#     optional float saturation = 3;
#   }
#   message Sound {
#     optional bool   noSound = 1;
#     optional string track   = 2;
#   }
#   message SoundList {
#     repeated string tracks = 1;
#   }
#   message Status {
#     optional float temperature = 2;
#     optional float humidity    = 3;
#   }
#
# HOW TO USE IT
# -------------
# Import and use like any protobuf message:
#
#   from .sound_light_pb2 import Message, Request, Settings, GetSettings, Sound
#
#   # Turn on and play a track
#   req = Request()
#   req.id = 1
#   req.settings.isOn = True
#   req.settings.sound.track = "White Noise"
#   msg = Message()
#   msg.request.CopyFrom(req)
#   await ws.send_bytes(msg.SerializeToString())
#
# HOW TO REGENERATE
# -----------------
# If Nanit updates their protocol and you need to update this file:
#
#   1. Update sound_light.proto (see the .proto content above)
#   2. pip install grpcio-tools
#   3. python -m grpc_tools.protoc -I. --python_out=. sound_light.proto
#   4. Copy the generated sound_light_pb2.py here and add this comment block
#
# COMPATIBILITY
# -------------
# The runtime version check that protoc normally emits has been removed so
# that this file works with both protobuf 4.x and 5.x, whichever HA ships.

from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x11sound_light.proto\"R\n\x07Message\x12\x19\n\x07request\x18\x01 \x01(\x0b\x32\x08'
    b'.Request\x12\x1b\n\x08response\x18\x02 \x01(\x0b\x32\t.Response\x12\x0f\n\x07\x62\x61'
    b'\x63kend\x18\x03 \x01(\x0c\"\x82\x01\n\x07Request\x12\n\n\x02id\x18\x01 \x01(\x05\x12'
    b'\x12\n\tsessionId\x18\xc8\x01 \x01(\t\x12!\n\x0bgetSettings\x18\x05 \x01(\x0b\x32\x0c'
    b'.GetSettings\x12\x1b\n\x08settings\x18\x06 \x01(\x0b\x32\t.Settings\x12\x17\n\x06status'
    b'\x18\n \x01(\x0b\x32\x07.Status\"~\n\x08Response\x12\x11\n\trequestId\x18\x01 \x01(\x05'
    b'\x12\x12\n\nstatusCode\x18\x02 \x01(\x05\x12\x15\n\rstatusMessage\x18\x03 \x01(\t\x12'
    b'\x1b\n\x08settings\x18\x04 \x01(\x0b\x32\t.Settings\x12\x17\n\x06status\x18\x06 \x01'
    b'(\x0b\x32\x07.Status\"V\n\x0bGetSettings\x12\x0b\n\x03\x61ll\x18\x01 \x01(\x08\x12\x13'
    b'\n\x0bsavedSounds\x18\x07 \x01(\x08\x12\x13\n\x0btemperature\x18\x08 \x01(\x08\x12\x10'
    b'\n\x08humidity\x18\t \x01(\x08\"\xb0\x01\n\x08Settings\x12\x12\n\nbrightness\x18\x01 '
    b'\x01(\x02\x12\x15\n\x05\x63olor\x18\x02 \x01(\x0b\x32\x06.Color\x12\x0e\n\x06volume'
    b'\x18\x03 \x01(\x02\x12\x15\n\x05sound\x18\x04 \x01(\x0b\x32\x06.Sound\x12\x0c\n\x04'
    b'isOn\x18\x05 \x01(\x08\x12\x1d\n\tsoundList\x18\x06 \x01(\x0b\x32\n.SoundList\x12\x13'
    b'\n\x0btemperature\x18\x07 \x01(\x02\x12\x10\n\x08humidity\x18\x08 \x01(\x02\"9\n\x05'
    b'Color\x12\x0f\n\x07noColor\x18\x01 \x01(\x08\x12\x0b\n\x03hue\x18\x02 \x01(\x02\x12'
    b'\x12\n\nsaturation\x18\x03 \x01(\x02\"\'\n\x05Sound\x12\x0f\n\x07noSound\x18\x01 \x01'
    b'(\x08\x12\r\n\x05track\x18\x02 \x01(\t\"\x1b\n\tSoundList\x12\x0e\n\x06tracks\x18\x01'
    b' \x03(\t\"/\n\x06Status\x12\x13\n\x0btemperature\x18\x02 \x01(\x02\x12\x10\n\x08'
    b'humidity\x18\x03 \x01(\x02'
)

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'sound_light_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals['_MESSAGE']._serialized_start = 21
    _globals['_MESSAGE']._serialized_end = 103
    _globals['_REQUEST']._serialized_start = 106
    _globals['_REQUEST']._serialized_end = 236
    _globals['_RESPONSE']._serialized_start = 238
    _globals['_RESPONSE']._serialized_end = 364
    _globals['_GETSETTINGS']._serialized_start = 366
    _globals['_GETSETTINGS']._serialized_end = 452
    _globals['_SETTINGS']._serialized_start = 455
    _globals['_SETTINGS']._serialized_end = 631
    _globals['_COLOR']._serialized_start = 633
    _globals['_COLOR']._serialized_end = 690
    _globals['_SOUND']._serialized_start = 692
    _globals['_SOUND']._serialized_end = 731
    _globals['_SOUNDLIST']._serialized_start = 733
    _globals['_SOUNDLIST']._serialized_end = 760
    _globals['_STATUS']._serialized_start = 762
    _globals['_STATUS']._serialized_end = 809
