# command-server

```
WARNING: If you're using this, don't
```

Client-server setup for running commands transparently in a different environment

## Protocol

The server is designed to process requests on a unix domain socket.

The request type is determined by the first line (the verb), followed by some
number of lines depending on the selected verb. Variables in the line should
be escaped as follows:

- `\` -> `\\`
- newline -> `\n`

```
[call|sig|reload|term]
<body>
```

### call

```
call
<dir>
<stdin>
<stdout>
<stderr>
<status-pipe>
<num-command-args>
<command>...
```

- `dir`: the working directory to use for the command
- `stdin, stdout, stderr`: files to use for standard IO when executing the
  request
- `status-pipe`: the pipe to write to to communicate to the client
- `num-command-args`: the number of lines to read for the `command`
- `command`: the actual request to execute (one or more lines)

To ack the request, the server writes an identifier representing the call into
the `status-pipe`, followed by a newline. Once the command is completed,
the server writes the status code to the `status-pipe`, again followed by a
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
<stdin>
<stdout>
<stderr>
<status-pipe>
```

Instructs the server to reload its configuration.

### term

```
term
```

Instructs the server to gracefully shutdown. Currently active requests will
continue, but pending requests will be interrupted.

## Implementation

To simplify implementation of the protocol, the server binary makes use of an
adapter pattern with an "executor" coprocess which dispatches commands
written to a named pipe.

### Executor API

The first three positional arguments passed to the executor are:
- file to read commands from
- file to write PIDs to
- file to write completions to

Following after that, additional positional arguments may be appended from
the invocation of `command_server.py`, or from the config file for the server.

In a loop, the executor reads commands in this format:

```
<request-id>
<dir>
<stdin>
<stdout>
<stderr>
<status-pipe>
<num-command-args>
<command>...
```

And writes out:

```
<pid>
```

Where `pid` is the process ID which is handling the execution of the command.

When the request is completed, will write the completion:

```
done <request-id>
```

### Executor shell lib

A POSIX-compliant shell implementation of the executor is provided at
`bin/lib/posix-executor-loop.sh`. The working directory, STDIO, and status
reporting are all handled for you. It expects 4 positional arguments:
- Function to call to execute the command. After calling, `$!` should be the PID
  handling the request
- The three files passed as the initial executor args
