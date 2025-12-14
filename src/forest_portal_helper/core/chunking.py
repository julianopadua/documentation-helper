from __future__ import annotations


def chunk_text_by_lines(text: str, max_chars: int, overlap_lines: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    lines = text.splitlines(True)
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    for line in lines:
        if cur and (cur_len + len(line) > max_chars):
            chunks.append("".join(cur))

            if overlap_lines > 0:
                tail = cur[-overlap_lines:] if len(cur) >= overlap_lines else cur
                cur = tail[:]
                cur_len = sum(len(x) for x in cur)
            else:
                cur = []
                cur_len = 0

        cur.append(line)
        cur_len += len(line)

    if cur:
        chunks.append("".join(cur))

    return chunks
