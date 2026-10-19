# Online match connection and CPU fallback

The warning “Network disconnected. Switching to CPU match.” can describe a frame
wait, a failed startup handshake, version mismatch, title synchronization failure,
or disagreement between game events. A working control connection and a green
server ping do not prove that the two cabinets are exchanging match data.

## Transport

The cabinet's checked sendto/recvfrom imports wrap game datagrams for the server's
UDP 20040 relay. WRL1 D carries destination seat, source seat and the unchanged
game payload. F returns the source seat/address and payload. R refreshes a seat's
return route; P/Q is the independent ping socket. This change keeps WRL1 compatible
with existing clients and servers.

The client formerly retained eight historical SOCKET numbers for its whole
lifetime. Windows could reuse a closed number for a new match or TCP connection;
the keepalive worker still attempted R on it. The server also let an alternate
same-IP R move a data route after five seconds without D, and refreshed the live
owner's expiry even when ignoring another socket's hello.

The fix retires client state through the game's validated closesocket import,
keeps peer addresses/counters per socket generation and selects only the newest
successful data socket for keepalives. The server pins a live data route against
alternate-port hellos. Same-IP D can still migrate immediately; an expired route
can be reclaimed. Only traffic from the selected owner refreshes that route.
Expiry is measured with monotonic time after the receive completes.

## Game decisions

Rev D's TIMEOUT_P2P defaults to 6 at option offset +0x164. Match setup multiplies
this by 500 and stores it at link +0xd8. The frame wait increments +0xd4 around
Sleep(1), making 6 nominally three seconds. Online starts now write 60 before the
first cabinet helper launches; local starts restore 6. The same path handles a
cabinet restart and an update whose SETUP step was skipped. These counts are not
a wall-clock maximum; scheduler delay can make the wait longer.

Other guards are independent: 600 failed update insertions before the peer becomes
healthy, a 70-second match-setup deadline, version checking and title-stage limits.
They have not been disabled or extended. The recorded reason mask distinguishes
them:

| Mask | Meaning |
|---|---|
| 0x1000 | Per-frame opponent wait exhausted |
| 0x2000 | Input/event comparison mismatch |
| 0x4000 | Title first-stage deadline |
| 0x8000 | Title synchronization deadline |
| 0x10000 | Invalid title progression |
| 0x40000 | Match setup deadline |
| 0x80000 | Version mismatch |
| 0x100000 | Peer health/disconnect |
| 0x200000 | Unmatched-event threshold |

The diagnostics only observe existing game state. They validate both singleton
roots and the peer/link vtables, guard reads with SEH, and recheck roots before
publishing a snapshot. They do not change game state, match results or club data.
Reasons are cumulative and a sample is not an atomic game-state snapshot.

## Verification and limits

Regression coverage includes the real cabinet-start path with scratch settings;
real UDP route migration, ping and a pause longer than the old five-second hold;
successive Windows socket closes/handle reuse; per-socket peer mapping; MSG_PEEK,
truncation, socket errors and concurrent operations. The original implementations
failed the corresponding routing/lifetime regressions before correction.

These tests demonstrate the corrected defects. They do not identify a past
incident that lacks correlated logs, and do not substitute for a two-PC match
with an intentionally interrupted internet connection. Both client and server
should be updated to obtain both corrections. A true disconnection can still
result in CPU fallback after the applicable budget.

WRL1 has no authenticated seat generation. A genuinely changed public IP may
remain blocked for the live owner's 30-second expiry, and a delayed D from an old
same-IP endpoint cannot be distinguished from legitimate port migration. Those
need a coordinated authenticated protocol change, not relaxed live-seat checks.
The diagnostics record actual routing decisions and game reasons so these cases
can be distinguished from socket lifetime defects.
