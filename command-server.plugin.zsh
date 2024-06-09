0="${ZERO:-${${0:#$ZSH_ARGZERO}:-${(%):-%N}}}"
0="${${(M)0:#/*}:-$PWD/$0}"

if [[ $PMSPEC != *f* ]]; then
    fpath+=("${0:h}/functions")
fi

if [[ $PMSPEC != *b* ]]; then
    path+=("${0:h}/bin")
    export PATH
fi

autoload -Uz \
    command-server-call \
    command-server-reload \
    command-server-start \
    command-server-terminate
