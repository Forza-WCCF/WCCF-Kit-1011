# -*- coding: utf-8 -*-
"""Stand-ins for RingEdge's background services, for WCCF 2010-11 on a normal PC. This version LOGS every question and
answers with guesses, to learn what Launcher1011.exe and the game ask (it grew out of _pcp_keychip.py, same protocol).

    python .work/_ringedge_services.py SECONDS OUT.log

Services and ports, read from Launcher1011.exe (2026-10-03):
    40100        master    (mxmaster: amMasterOpen ... mxmaster.foreground.getcount / next)       FUN_004171d0
    40102/40103  installer (mxinstaller: amInstallSendAndRecvEx, amInstallResponseCheck)          FUN_00414c30
    40106/40107  keychip   (mxkeychip: keychip.version, keychip.appboot.*, keychip.billing.* ...) FUN_0040ff70
The first port of a pair is text, the second binary (binary is only logged).
PCP, as read from the launcher's client: the server greets with '>'; a request is one line "key=value&key=value\\r\\n"
('?' asks for a value); the answer is a line in the same form FOLLOWED BY the prompt '>' again (needed: see below).
The launcher mostly sends one request per connection.
Values marked DISC come from the disc; everything else is a GUESS until a run shows otherwise.
"""
import socket
import sys
import threading
import time

# Values from sega.bsnk.me/ringedge/software/mx/mxkeychip (DOC), cross-checked against the launcher's code; DISC = from
# the game files. systemflag is a bit field: bit0 dev-keychip, bit2 ALL.Net, bit3 net-delivery, bit4 binding,
# bit5 billing, bit6 rental - 0 keeps net and billing OFF.
ANSWERS = {
    "keychip.status": "available",                  # DOC (init / available / error)
    "keychip.version": "0104",                      # DOC (= version 1.4)
    "keychip.appboot.gameid": "SBWG",               # DISC
    "keychip.appboot.platformid": "AAL",            # DOC/DISC (AAL = RingEdge; AALO_0037 OS image)
    "keychip.appboot.region": "1",                  # DOC (Japan=1, USA=2, Export=4, China=8)
    "keychip.appboot.modeltype": "01",              # DOC (01 = RingEdge, 02 = RingEdge2; 2-digit hex)
    "keychip.appboot.networkaddr": "192.168.46.0",  # DISC (strings)
    "keychip.appboot.systemflag": "00",             # DOC (byte; 00 = no dev/net/billing)
    "keychip.appboot.formattype": "1",              # DOC (1 supported by mxsegaboot)
    "keychip.appboot.dvdflag": "00",                # DOC (00 or 01; 2-digit hex)
    "keychip.billing.keyid": "A72E-0123456",        # DOC format (A72E-0123456 example)
    "keychip.billing.mainid": "A72E-0123456",       # DOC (write-once; locks to mainboard)
    "keychip.billing.playcount": "0",               # DOC (read / increment-by-1)
    "keychip.billing.playlimit": "1024",            # GUESS (write needs a 128-byte signature)
    "keychip.billing.nearfull": "0",                # DOC (lower 16 = plays left, upper 16 = accounting mode)
    "mxmaster.foreground.getcount": "1",            # GUESS
}
# Extra fields some answers must carry, read from the launcher's parsers:
# master (FUN_00417db0): the first keyword must echo the question (FUN_00417a60), an optional "code" (missing or 0 =
# OK, 1-5 = errors; FUN_004179d0), then "count"; for getcount=2 (amMasterGetFirstApplicationStart) count < 2 means
# "this is the first application start". Without "count" the launcher set error bits and exited (run 2026-10-03).
EXTRA = {
    "mxmaster.foreground.getcount": "count=1",
}
TEXT = {40100: "master", 40102: "installer", 40106: "keychip"}
BINARY = {40103: "installer-bin", 40107: "keychip-bin"}
AMNET = {40104: "amnetwork"}
# amNetwork (amNetwork Ver.1.06) on 40104 - the game's boot state machine (wccf::NetworkStartUpWaitSequenceNode)
# sends request=query_dhcp_status&if=0 etc. and will not leave "GET DHCP STATUS" until it gets
# response=query_dhcp_status&result=0&dhcp_status=<1..4>. dhcp_status=3 walks straight through (0 stalls).
AMNET_FIELDS = {
    "query_dhcp_status":   "dhcp_status=3",        # 3 = clean advance (0 stalls; 1/2/4 take detours)
    "update_dhcp_status":  "",                     # the game SENDS status=1/5; reply is just result=0
    "query_nic_status":    "status=3",             # 3 = configured
    "query_ip_address":    "ip_address=192.168.46.46",
    "query_subnetmask":    "subnetmask=255.255.255.0",
    "query_gateway":       "gateway=192.168.46.254",
    "query_primary_dns":   "primary_dns=192.168.46.254",
    "query_secondary_dns": "secondary_dns=192.168.46.254",
    "query_mac_address":   "mac_address=0123456789AB",
}

LOG = None
LOCK = threading.Lock()
T0 = time.time()
DURATION = 0


def log(s):
    with LOCK:
        LOG.write("%7.2f  %s\n" % (time.time() - T0, s))
        LOG.flush()


def answer(line):
    out = []
    keychip = False
    for part in line.split("&"):
        k, v = (part.split("=", 1) + [""])[:2] if "=" in part else (part, "")
        k, v = k.strip(), v.strip()
        if k.startswith("keychip."):
            keychip = True
        if v == "?" or (k in ANSWERS and k not in EXTRA):
            out.append("%s=%s" % (k, ANSWERS.get(k, "0")))
        else:
            out.append("%s=%s" % (k, v))
        if k in EXTRA:
            out.append(EXTRA[k])
    reply = "&".join(out)
    # The game's amDongle keychip client (client FUN_008281b0 / FUN_00458c40, the state-5 black-screen
    # blocker) requires result=0 to treat a reply as complete; the launcher's mxkeychip path tolerated
    # its absence. Append it for keychip queries so the game's keychip setup finishes.
    if keychip and "result=" not in reply:
        reply += "&result=0"
    return reply


def text_client(conn, addr, name):
    log("%-13s %s connected" % (name, addr[1]))
    try:
        conn.sendall(b">")
        buf = b""
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.rstrip(b"\r").decode("latin-1")
                if not line:
                    continue
                reply = answer(line)
                log("%-13s ask  %s" % (name, line))
                log("%-13s say  %s" % (name, reply))
                # the prompt AGAIN after every answer: without it the launcher spins at 100% after its first
                # question (run 2026-10-03, this script's first version); with it, it went on asking.
                conn.sendall(reply.encode("latin-1") + b"\r\n>")
    except OSError:
        pass
    finally:
        conn.close()


def amnet_answer(line):
    kv = {}
    for part in line.split("&"):
        k, v = (part.split("=", 1) + [""])[:2]
        kv[k.strip()] = v.strip()
    cmd = kv.get("request", "")
    parts = ["response=%s" % cmd, "result=0"]
    field = AMNET_FIELDS.get(cmd, "")
    if field:
        parts.append(field)
    if "if" in kv:
        parts.append("if=%s" % kv["if"])          # echo the NIC index the game keyed the query by
    return "&".join(parts)


def amnet_client(conn, addr, name):
    # amNetwork/amDongle PCP: greet '>', then reply each request with just "line\r\n" and NO trailing
    # '>' prompt. The trailing '>' (needed by the launcher's keychip/master) is EXTRA data that keeps
    # this client's recv phase open, so it never closes its own side; its transaction result (+0x14)
    # stays 1 and the game's state-1 gate (result != 1) never passes. Reply clean and let the client close.
    log("%-13s %s connected" % (name, addr[1]))
    try:
        conn.sendall(b">")
        buf = b""
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.rstrip(b"\r").decode("latin-1")
                if not line:
                    continue
                reply = amnet_answer(line)
                log("%-13s ask  %s" % (name, line))
                log("%-13s say  %s" % (name, reply))
                conn.sendall(reply.encode("latin-1") + b"\r\n")
    except OSError:
        pass
    finally:
        conn.close()


def binary_client(conn, addr, name):
    log("%-13s %s connected" % (name, addr[1]))
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            log("%-13s got %d bytes: %s" % (name, len(data), data[:64].hex()))
    except OSError:
        pass
    finally:
        conn.close()
        log("%-13s %s closed" % (name, addr[1]))


def serve(port, name, handler):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError as e:
        log("%-13s CANNOT LISTEN on %d: %s" % (name, port, e))
        return
    s.listen(16)
    s.settimeout(1.0)
    log("%-13s listening on 127.0.0.1:%d" % (name, port))
    while time.time() - T0 < DURATION:
        try:
            conn, addr = s.accept()
        except socket.timeout:
            continue
        threading.Thread(target=handler, args=(conn, addr, name), daemon=True).start()
    s.close()


def main(argv):
    global LOG, DURATION
    if len(argv) != 2 or not argv[0].isdigit():
        print(__doc__)
        return 2
    DURATION = int(argv[0])
    LOG = open(argv[1], "w", encoding="utf-8")
    log("RingEdge services stand-in (logs and guesses), for %d s" % DURATION)
    threads = [threading.Thread(target=serve, args=(p, n, text_client), daemon=True) for p, n in TEXT.items()]
    threads += [threading.Thread(target=serve, args=(p, n, amnet_client), daemon=True) for p, n in AMNET.items()]
    threads += [threading.Thread(target=serve, args=(p, n, binary_client), daemon=True) for p, n in BINARY.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log("stopped")
    LOG.close()
    print("done; log in %s" % argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
