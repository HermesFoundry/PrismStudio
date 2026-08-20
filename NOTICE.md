# Notice

PrismStudio is a fork of **Code - OSS**, the open source project that
Microsoft's Visual Studio Code is built from.

- Upstream: https://github.com/microsoft/vscode
- Upstream licence: MIT, `LICENSE.txt` in this repository
- Upstream copyright: Copyright (c) 2015 - present Microsoft Corporation
- Forked from upstream commit `773e6102d24184f4f9eaee9482d25cb85a6d6514`
  (Code - OSS 1.135.0)

This repository holds that upstream tree as its first commit rather than the
whole of upstream's history, because the clone it was taken from was a shallow
one. The commit above is the exact point it was taken from, so anyone can
verify what was changed by diffing against it.

`LICENSE.txt` and `ThirdPartyNotices.txt` are kept exactly as they arrived,
because that is what the MIT licence asks of anyone who redistributes the
code: the notice travels with it.

## This is not Visual Studio Code

PrismStudio is **not** affiliated with, endorsed by, or sponsored by
Microsoft, and it is not Microsoft's Visual Studio Code.

Microsoft, Visual Studio, Visual Studio Code and their logos are trademarks of
Microsoft Corporation. The MIT licence covers the source code; it does not
grant any right to those names or marks. So none of them are used here: the
name, the icons and the artwork in this repository are Hermes Foundry's own,
and the Microsoft branding that ships in the upstream tree is replaced rather
than merely hidden — see `branding/`.

## Extensions come from Open VSX

Microsoft's extension marketplace is licensed for use with Microsoft's own
products, so a build that is not one of theirs may not use it. PrismStudio
points at [Open VSX](https://open-vsx.org) instead. Extensions published only
to Microsoft's marketplace, and Microsoft's own proprietary extensions, are
therefore not installable here. That is a consequence of the licensing, not an
oversight.

## What is changed from upstream

Everything of ours is additive and kept in its own place, so that merging
upstream stays a merge:

| Change | Where |
|---|---|
| Product name, identifiers, data folder, URL protocol, icons | `branding/product.prism.json`, applied by `branding/brand.py` |
| Extension gallery pointed at Open VSX | same |
| A built-in Claude integration | `extensions/prism-claude/` |
| Build helpers, including dependency headers without root | `branding/build.sh`, `branding/localdeps.sh` |

`branding/brand.py --revert` puts the upstream `product.json` back.

## Licence of this fork

MIT, the same as upstream. Our own additions are offered under the same terms.
The application icon is Hermes Foundry's artwork and is not covered by that
grant.
