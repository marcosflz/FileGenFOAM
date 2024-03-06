import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import  ttk


varDim = {
    'U':        '[0 1 -1 0 0 0 0];',
    'p':        '[0 2 -2 0 0 0 0];',
    'nut':      '[0 2 -1 0 0 0 0];',
    'nuTilda':  '[0 2 -1 0 0 0 0];',
    'k':        '[0 2 -2 0 0 0 0];'
    }


files = None

def get_boundary_names(file_path):
    boundary_names = []
    with open(file_path, 'r') as file:
        boundary_section = False
        for line in file:
            line = line.rstrip()
            if line.startswith("FoamFile") or line.startswith("//"):
                continue
            if line == "(":  # Inicio de la sección de límites
                boundary_section = True
                continue
            if line == ")":  # Fin de la sección de límites
                boundary_section = False
                continue
            if boundary_section and not ("{" in line or "}" in line or line.endswith(";")):  # Línea que contiene el nombre del límite
                boundary_name = line.split()[0]
                boundary_names.append(boundary_name)
    return boundary_names


def gen_files(var,boundaries):
    
    if var not in varDim:
        raise ValueError(f"La variable '{var}' no está definida en varDim")

    content = f"""/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\\\    /   O peration     | Website:  https://openfoam.org
    \\\\  /    A nd           | Version:  10
     \\\\/     M anipulation  |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       volVectorField;
    object      {var};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

dimensions      {varDim[var]}

internalField   uniform (0 0 0);

boundaryField
{{
"""

    # Agregar los nuevos elementos al contenido
    for bound in boundaries:
        content += f"""
    {bound}
    {{
        type           /* type */;
        value          /* value */;
    }}
"""

    content += """
}

// ************************************************************************* //
"""
    return content


class writeFiles:
    def __init__(self, boundary):
        self.U          = gen_files('U',boundary)
        self.p          = gen_files('p',boundary)
        self.nut        = gen_files('nut',boundary)
        self.nuTilda    = gen_files('nuTilda',boundary)
        self.k          = gen_files('k',boundary)


def clearText():
    textBox.delete('1.0', tk.END)

def deleteFile():
    clearText()
    global files
    files = None

def importFile():
    global files
    file_path = filedialog.askopenfilename()
    def inner():
        if file_path:
            with open(file_path, 'r') as file:
                new_elements = file.readlines()
                textBox.delete('1.0', tk.END)
                textBox.insert(tk.END, "".join(new_elements))
    
    files = writeFiles(get_boundary_names(file_path))
    return inner()
        


def textBox_Var(var):
    global files
    try:
        clearText()
        textBox.insert(tk.END,getattr(files, var))
    except Exception:
        return messagebox.showinfo("Warning", "No boundary file selected.")
    

def exportFile():

    content = textBox.get("1.0", tk.END)
    lines = content.split('\n')

    for line in lines:
        if 'object' in line:
            export_name = str(line.split()[-1].strip(";"))
            with open(export_name, 'w') as file:
                file.write(content)


def update_button_text():
    selected_item = item_list.get()         # Obtener el elemento seleccionado en item_list
    writeButton.config(text='Write ' + selected_item)  # Actualizar el texto del botón con el elemento seleccionado







# Crear la ventana principal
window = tk.Tk()
window.title("OpenFOAM File Generator")
window.resizable(False, False)  # Bloquear el cambio de tamaño tanto en el eje X como en el eje Y
h, w = 30,80

# Área de texto para mostrar el contenido del archivo cargado
textBox = tk.Text(window, height=h, width=w)
textBox.grid(row=1, column=0, columnspan=3, padx=0, pady=0)

# Botón para seleccionar archivo
boundary_import_button = tk.Button(window, text="Select File", command=lambda:importFile())
boundary_import_button.grid(row=0, column=0, padx=5, pady=5, sticky="nwse")


items = list(list(varDim.keys()))
item_list = ttk.Combobox(window, values=items) 
item_list.set(items[0])  
item_list.grid(row=0, column=1, sticky='nwse')  
item_list.bind("<<ComboboxSelected>>", lambda event: update_button_text())

# Botón para escribir archivo
writeButton = tk.Button(window, text="Write U", command=lambda:textBox_Var(item_list.get()))
writeButton.grid(row=0, column=2, padx=5, pady=5, sticky="nwse")

# Botón para borrar el contenido del archivo importado
deleteFile_button = tk.Button(window, text="Delete File", command=lambda:deleteFile())
deleteFile_button.grid(row=2, column=0, padx=5, pady=5, sticky="nwse")

# Botón para borrar el contenido del cuadro de texto
deleteFile_button = tk.Button(window, text="Clean Text Box", command=lambda:clearText())
deleteFile_button.grid(row=2, column=1, padx=5, pady=5, sticky="nwse")

# Botón para exportar
export_button = tk.Button(window, text="Export Text Box", command=lambda:exportFile())
export_button.grid(row=2, column=2, padx=5, pady=5, sticky="nwse")


# Ejecutar la interfaz gráfica
window.mainloop()