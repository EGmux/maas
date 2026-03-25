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
## Scratch

Reduzindo tempo de provisionamento e viabilizando suporte para dual boot, um estudo de caso na implantação e customização da ferramenta MAAS w

Reduzindo tempo de provisionamento em sistemas bare-metal e viabilizando suporte para dual boot, um estudo de caso na implantação e extensibilidade do Metal as a Service(MAAS)


Proposta de TCC
Atualmente há um esforço enorme em tratar o ambiente de desenvolvimento como descartável, vide ferramentas de IaC (Infrastructure as Code) como Ansible (RedHat), Terraform (Hashicorp), Helm (Google) etc. No entanto, embora existam diversas ferramentas que provisionam máquinas virtuais, containers e até mesmo aplicações, há uma escassez de ferramentas para provisionamento bare metal que possuam código aberto, suporte empresarial e considerem casos de uso de ambientes on-premises e nuvens privadas.

A escassez de ferramentas impacta não somente o público empresarial, mas também o público acadêmico, visto que o setor de suporte precisa dedicar tempo extra para completar tickets relacionados a formatação de máquinas e provisionamento de laboratórios, além de um orçamento mais limitado. Devido à inerente complexidade dessas tarefas, a equipe técnica pode acabar perdendo horas ou até mesmo dias, o que impacta nas métricas de produtividade do setor, reduzindo a agilidade operacional.

Este trabalho visa introduzir o Metal as a Service (MAAS) como uma ferramenta adequada para solução do problema. Desenvolvido pela Canonical, o software é uma solução de código aberto que possibilita provisionamento automatizado de ambientes bare-metal. Para tal, o presente trabalho apresenta dois estudos de caso: os desafios de implantar tal ferramenta no Cin-UFPE e a contribuição para o projeto através da implementação da feature de dual-boot.


---


