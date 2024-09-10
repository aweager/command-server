0="${ZERO:-${${0:#$ZSH_ARGZERO}:-${(%):-%N}}}"
0="${${(M)0:#/*}:-$PWD/$0}"

if [[ $PMSPEC != *b* ]]; then
    path+=("${0:h}/bin")
    export PATH
fi
