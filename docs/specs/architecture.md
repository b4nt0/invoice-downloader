# AID architecture

AID consists of the orchestrator script, service modules, and setup scripts.

## Orchestrator script

The orchestrator script reads the configuration and runs automation for the services required.

## Service modules

Service modules are the main element of AID. 

Each service module is responsible for a particular service that generates invoices, such as AWS, Heroku, Google Cloud, or OpenAI.

The input to a service module is the date interval for which the invoices are required, the download target, and the file naming schema.

The output of a service module is a list of file paths where the invoice PDFs are downloaded.

## Setup scripts

Setup scripts are miscellaneous scripts that deal with configuration files, output directories, and other matters that are required to run AID.
