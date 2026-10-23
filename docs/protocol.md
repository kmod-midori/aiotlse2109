# Protocol and verification

[Back to README](../README.md)

Live-tested on two **TL-SE2109** switches running
**1.8.0 Build 20250331 Rel.32620**, including 10 Mbps, 1 Gbps, and 2.5 Gbps
links. The implementation
reads `info_ds` and `port_info` from `MainRpm.htm` and authenticates through
`logon.cgi` with the firmware's `cryp_new.js` password encoding. A firmware
that explicitly declares `encryptType = 5` uses MD5 instead; that path is
covered by simulated HTTP tests, not a second live device.

The web interface is a firmware-specific protocol. Other firmware versions
may need parser or authentication updates. Data literals are parsed without
executing JavaScript. The test fixture is based on an observed response with
network identifiers replaced by documentation addresses.

SessionID cookies are handled explicitly so literal IP addresses work with
aiohttp's default cookie policy. The firmware supplies traffic rates in kbps;
the parser converts them to bps. Unsupported data or speed codes raise an
error instead of producing fabricated measurements.

Exporter metrics are generated afresh for each response, following the
[Prometheus exporter guidance](https://prometheus.io/docs/instrumenting/writing_exporters/).
