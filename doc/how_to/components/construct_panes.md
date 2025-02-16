# Construct Panes

There are two main ways to construct a pane - explicitly or automatically.

To explicitly construct a pane, use one of the pane types listed in the [reference gallery](../../reference/index.html#panes). For example, you can create a Markdown pane as follows:

```{pyodide}
import panel as pn
pn.extension() # for notebook

pn.pane.Markdown('''
# H1
## H2
### H3
''')
```

Alternatively, you can create a pane using the `pn.panel()` utility to automatically infer the pane type from the object being passed as the argument:

```{pyodide}
png = pn.panel('https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png', width=500)

png
```

:::{admonition} See Also
:class: seealso

* Learn more about Panes in the <a href="../../background/components/components_overview.html#panes">Background for Components</a>
:::
