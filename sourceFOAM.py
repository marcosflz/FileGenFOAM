def folder0(var,varDim,varTyp,boundaries):

    type = varTyp[var]
    dim = varDim[var]

    if type == 'volVectorField':
        value = '(0 0 0)'

    elif type == 'volScalarField':
        value = '0'

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
    class       {type};
    object      {var};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

dimensions      {dim};

internalField   uniform {value};

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