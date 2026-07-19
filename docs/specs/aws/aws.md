# AWS

AWS uses lots of redirects. The module must wait for the redirects to converge. 

Once converged, the module must select the correct billing perdiods from the dropdown and click the Print button. In the dialog that pops up, the script must click Print once again to get the browser's print to PDF dialog and save the file.

The output of AWS is pretty noisy, to clean it up, the module must leave two essential elements:

- A `<div>` with `data-testid="summary-card"`

- A `<div>` with `data-testid="ANY_STRING-charges-by-service"`
(the `ANY_STRING` part is variable)