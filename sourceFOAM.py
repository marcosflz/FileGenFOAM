def folder0(var,varDim,boundaries):
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