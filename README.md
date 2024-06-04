# command-server

Client-server setup for running commands transparently in a different environment

## Protocol

The server is designed to process requests on a unix domain socket.

The request type is determined by the first line (the verb), followed by some
number of lines depending on the selected verb. Variables in the line should
be escaped as follows:

- `\` -> `\\`
- newline -> `\n`

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
<num-command-args>
<command>...
```

- `dir`: the working directory to use for the command
- `stdin, stdout, stderr`: files to use for standard IO when executing the
  request
- `response-pipe`: the pipe to write to to communicate to the client
- `num-command-args`: the number of lines to read for the `command`
- `command`: the actual request to execute (one or more lines)

To ack the request, the server writes an identifier representing the call into
the `response-pipe`, followed by a newline. Once the command is completed,
the server writes the status code to the `response-pipe`, again followed by a
newline.

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

When first stood up, a single file name `queue-ops` will be written to standard
input, followed by a newline.

In a loop, the executor reads on standard input:

```
<request-id>
<dir>
<stdin>
<stdout>
<stderr>
<response-pipe>
<num-command-args>
<command>...
```

Writing to standard output:

```
<pid>
```

Where `pid` is the process ID which is handling the execution of the command.

When the request is completed, will write to `queue-ops`:

```
done <request-id>
```

### Executor shell lib

A POSIX-compliant shell implementation of the executor is provided at
`bin/lib/posix-executor-loop.sh`. It expects a function (or other command)
named `execute-command` to be defined, which accepts the `command` as its
arguments. The working directory, STDIO, and status reporting are all handled
for you.
