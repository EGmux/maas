# NOTES:  about maas workflow for single boot

## Context
- Why does this project exist?
- What problem does it solve?
- Who is it for?

## Commands
- `cmd1` - what it does
- `cmd2` - what it does

## Configs
- `path/to/config` - what it controls

## Quirks
- Things that don't work as expected
- Workarounds
- Gotchas

## TODO
- [ ] 

## Notes
- so maas entry point is in "src/maasserver/__init__py"
- also the entrypoint imports from 
    maasserver.utils -> threads, orm
    twisted.internet -> reactor

- from this we go to "src/maasserver/management/commands/runserver.py"
- call in Command(BaseRunServerCommand) the run method that starts the server, thus our next stop

- and from this we go to "src/maasserver/start_up.py"
    - we look at start_up method, extremely resilient and async
    - inner_start_up() is a database-guarded initialization function that runs exclusively on the master region controller. It loads built-in commissioning scripts, registers this region in the database, sets up shared secrets and cluster certificates, validates the commissioning OS distro, and initializes image storage—all within a transaction to prevent concurrent execution across multiple region controllers.
    MAAS use's AMP-Async Message Protocol and has a dedicated IPC import in maasserver/ipc.py
- from here we go to "src/maasserver/eventloop.py"
- maas has the concepts of "workflows" triggers then in "src/maasserver/worflow/__init__.py"
- from here we go to "src/maasserver/models/node.py" to find what a node is
    **this file has start_commissioning workflow!**

## Topic: [ongoing]
type: parallel
depends: []
---
content: Find ActiveDiscoveryService
notes: src/maasserver/eventloop.py
---

## The MAAS region controller's Heart: [ongoing]
type: sequential
depends: [ActiveDiscoveryService]
---
content: RegionEventLoop
notes: src/maasserver/eventloop.py
---

## The DiscoveryService: [reference]
type: sequential
depends: [RegionEventLoop]
---
content: src/maasserver/regiondservices/active_discovery.py
notes: is a twisted TimerService,periodically,coordinates with rackcontrollers
---

## Where is the definition of DiscoveryService(Spoiler: is in the DB): [ongoing]
type: parallel
depends: []
---
content: this stuff is located in maaserver/models/config.py
notes: 
---

## Scratch

---
