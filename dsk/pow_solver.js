const fs = require('fs');
const path = require('path');

async function solve() {
    const wasmPath = path.join(__dirname, 'wasm', 'sha3_wasm_bg.7b9ca65ddd.wasm');
    const wasmBuffer = fs.readFileSync(wasmPath);

    // Config from command line
    const config = JSON.parse(process.argv[2]);
    const { algorithm, challenge, salt, difficulty, expire_at } = config;
    const prefix = `${salt}_${expire_at}_`;

    let wasm;
    const imports = {
        wbg: {
            __wbindgen_throw: (arg0, arg1) => {
                throw new Error("WASM Throw");
            }
        }
    };

    const { instance } = await WebAssembly.instantiate(wasmBuffer, imports);
    wasm = instance.exports;

    const memory = wasm.memory;

    function writeToMemory(str) {
        const encoded = Buffer.from(str, 'utf-8');
        const ptr = wasm.__wbindgen_export_0(encoded.length, 1);
        const view = new Uint8Array(memory.buffer);
        view.set(encoded, ptr);
        return [ptr, encoded.length];
    }

    const [challengePtr, challengeLen] = writeToMemory(challenge);
    const [prefixPtr, prefixLen] = writeToMemory(prefix);

    // Allocate 16 bytes for the return values on the stack
    const retptr = wasm.__wbindgen_add_to_stack_pointer(-16);

    try {
        wasm.wasm_solve(
            retptr,
            challengePtr,
            challengeLen,
            prefixPtr,
            prefixLen,
            parseFloat(difficulty)
        );

        const view = new DataView(memory.buffer);
        const status = view.getInt32(retptr, true);

        if (status === 0) {
            console.log(JSON.stringify({ answer: null }));
            return;
        }

        const value = view.getFloat64(retptr + 8, true);
        console.log(JSON.stringify({ answer: Math.floor(value) }));
    } finally {
        wasm.__wbindgen_add_to_stack_pointer(16);
    }
}

solve().catch(err => {
    console.error(err);
    process.exit(1);
});
