# command-server

Client-server setup for running commands transparently in a different environment

## Implementation details

The server is designed to process requests in order, one at a time, from a unix
domain socket.

### Listener

Listens on a socket for requests. The format of a request is:

```
<stdin> <stdout> <stderr> <response-pipe> <client-id>
<command>
```

- `client-id`: the PID of the client (used for logging)
- `response-pipe`: the file to write to when communicating to the client
- `stdin, stdout, stderr`: files to use for standard IO when executing the
  request
- `command`: the actual request to execute

Once the command is completed, the server writes the status code to
the `response-pipe`.

Following the command, the client will send a code indicating how it wants to
detach. The code tells the server what to do with the running request:

- `-1`: background the requests
- `0`: request was completed
- `1`: interrupt and cancel the requests

### Executor loop

Reads commands from $1 (in the format described above) and executes them,
writing 'done' to $2 when it has finished each request.

### Call

Calls the server through the socket. Responsible for forwarding file descriptors
through FIFOs or ttys.
