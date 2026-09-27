import struct

from PIL import Image, ImageDraw

from remote_agent.capture import DELTA, HEADER, KEYFRAME, TILE, FrameEncoder, scale_to_width


def parse(msg):
    kind, w, h, count = HEADER.unpack_from(msg, 0)
    off, tiles = HEADER.size, []
    for _ in range(count):
        x, y, tw, th, n = TILE.unpack_from(msg, off)
        off += TILE.size
        tiles.append((x, y, tw, th))
        assert msg[off:off + 2] == b"\xff\xd8"  # JPEG başlangıcı
        off += n
    assert off == len(msg)
    return kind, w, h, tiles


def test_keyframe_then_delta_then_nothing():
    enc = FrameEncoder(tile=64)
    img = Image.new("RGB", (300, 200), "white")
    kind, w, h, tiles = parse(enc.encode(img, 60))
    assert (kind, w, h, tiles) == (KEYFRAME, 300, 200, [(0, 0, 300, 200)])

    assert enc.encode(img.copy(), 60) is None

    img2 = img.copy()
    ImageDraw.Draw(img2).rectangle([70, 70, 80, 80], fill="red")  # tek döşeme (64..128)
    kind, _, _, tiles = parse(enc.encode(img2, 60))
    assert kind == DELTA and tiles == [(64, 64, 64, 64)]


def test_adjacent_tiles_merge_and_edges_clip():
    enc = FrameEncoder(tile=64)
    img = Image.new("RGB", (300, 200), "white")
    enc.encode(img, 60)
    img2 = img.copy()
    ImageDraw.Draw(img2).rectangle([130, 150, 299, 160], fill="blue")
    _, _, _, tiles = parse(enc.encode(img2, 60))
    # 2., 3. ve 4. sütundaki döşemeler tek dikdörtgende birleşir; sağ kenar 300'e kırpılır
    assert tiles == [(128, 128, 172, 64)]


def test_size_change_forces_keyframe():
    enc = FrameEncoder()
    enc.encode(Image.new("RGB", (100, 100)), 50)
    kind, w, h, _ = parse(enc.encode(Image.new("RGB", (120, 90)), 50))
    assert (kind, w, h) == (KEYFRAME, 120, 90)


def test_scale_to_width():
    img = Image.new("RGB", (3840, 2160))
    assert scale_to_width(img, 1920).size == (1920, 1080)
    assert scale_to_width(img, 0) is img
