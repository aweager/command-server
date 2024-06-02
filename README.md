# command-server

Client-server setup for running commands transparently in a different environment

## Protocol

The server is designed to process requests on a unix domain socket.

The request type is determined by the first line (the verb), followed by some
number of null-terminated "lines" depending on the selected verb. In the below
code samples, read all newlines as null bytes.

```
[call|sig|reload]
<body>
```

### call

```
call
<dir>
<stdin>
<stdout>
<stderr>
<response-pipe>
<command>
```

- `dir`: the working directory to use for the command
- `stdin, stdout, stderr`: files to use for standard IO when executing the
  request
- `response-pipe`: the pipe to write to to communicate to the client
- `command`: the actual request to execute, usually a POSIX-quoted string

To ack the request, the server writes an identifier representing the call into
the `response-pipe`, followed by a null byte. Once the command is completed,
the server writes the status code to the `response-pipe`, again followed by a
null byte.

### sig

```
sig
<request-id>
<signal>
```

Send the specified `signal` to the request with the given ID. The following
signals from the [POSIX standard](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/signal.h.html)
are supported:

- `HUP`
- `INT`
- `QUIT`
- `TERM`

### reload

```
reload
<dir>
<stdin>
<stdout>
<stderr>
<response-pipe>
```

Instructs the server to reload its configuration, and use that configuration for
all future requests.

## Implementation

To simplify implementation of the protocol, the server binary makes use of an
adapter pattern with an "executor" coprocess which dispatches commands
written to its standard input.

### Executor API

When first stood up, a single file name `queue-ops` will be written to standard input.

On Standard input:

```
<request-id>
<dir>
<stdin>
<stdout>
<stderr>
<response-pipe>
<command>
```

Writing to standard output, followed by a newline:

```
<pid>
```

Where `pid` is the process ID which is handling the execution of the command.

When the request is completed, will write to `queue-ops`:

```
done
<request-id>
```

### Executor shell lib

There are three provided implementations of the executor API in the form of
shell scripts, which may be sourced by their respective shells:

#### POSIX

`bin/lib/posix-executor-loop.sh` expects a shell function (or other command)
named `execute-command` to be defined, which accepts the `command` as its only
argument. The working directory, STDIO, and status reporting are all handled
for you.

WARNING: this script is not currently actually POSIX-compliant, because it
relies on the `-d` option of `read` to split on null bytes.

#### bash

`bin/lib/bash-executor-loop.bash` wraps around the POSIX implementation. It
assumes the `command` is a sequence of shell-quoted arguments. The function
`execute-bash-command` will be handed those arguments for execution.

#### zsh

`bin/lib/zsh-executor-loop.zsh` wraps around the POSIX implementation. It
assumes the `command` is a sequence of shell-quoted arguments. The function
`execute-zsh-command` will be handed those arguments for execution.
